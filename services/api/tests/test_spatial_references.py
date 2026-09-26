import hashlib
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from PIL import Image

from test_image_batches import environment
from test_image_input_modes import prepare
from viral_dna_api.composition import CompositionGuide, CompositionUpdate
from viral_dna_api.image_generation.catalog import load_image_model_catalog
from viral_dna_api.image_generation.contracts import AdapterIdentity
from viral_dna_api.image_generation.gateway import ImageGenerationGateway, ImageGenerationGatewayError
from viral_dna_api.models import (GenerationCostSource, ImageExecutionMode, PromptAssetMention, ReferenceAsset,
                                 ReferenceBinding, ShotVisualBeatUpdate, WorkflowItemStatus)
from viral_dna_api.production import ProductionService, ProductionServiceError
from viral_dna_api.reference_purposes import scoped_bindings
from viral_dna_api.spatial_references import SpatialReferenceUpdate, apply_spatial_reference, spatial_reference_state
from viral_dna_api.style_library import StyleLibrary, StyleDefinition, StyleWrite
from viral_dna_api.style_reference import image_style_reference


async def asset(env, name='空间样例'):
    result = ReferenceAsset(project_id=env.project.id, name=name, type='scene', relative_path='references/test.png',
                            mime_type='image/png', width=16, height=16, sha256='a' * 64, rights_confirmed=True)
    await env.store.save_reference_asset(result)
    return result


async def apply(env, ref, beats, replace=False, **extra):
    state = await spatial_reference_state(env.service, env.project.id)
    return await apply_spatial_reference(env.service, env.project.id, SpatialReferenceUpdate(**{
        'expected_revision_id': state['revision_id'], 'expected_context_id': state['context_id'],
        'reference_asset_id': ref.id, 'visual_beat_ids': beats, 'replace_existing': replace, **extra}))


@pytest.mark.asyncio
@pytest.mark.parametrize('durable', [False, True])
async def test_bulk_atomic_scopes_reload_and_history_survive(tmp_path, monkeypatch, durable):
    env = await environment(tmp_path, monkeypatch, count=3, durable=durable)
    ref = await asset(env)
    first, second, untouched = env.shots
    approved = uuid4()
    first = first.model_copy(update={'visual_beats': [first.visual_beats[0].model_copy(update={
        'approved_image_candidate_id': approved, 'image_status': WorkflowItemStatus.APPROVED})]})
    await env.store.save_shot_plan(first)
    targets = [first.visual_beats[0].id, second.visual_beats[0].id]
    state = await apply(env, ref, targets)
    for shot in (first, second):
        saved = await env.store.get_shot_plan(shot.id)
        assert saved.visual_beats[0].image_prompt_mentions[-1].role == 'spatial'
        assert saved.visual_beats[0].image_prompt.startswith('@') or '@' in saved.visual_beats[0].image_prompt
    assert (await env.store.get_shot_plan(first.id)).visual_beats[0].approved_image_candidate_id == approved
    assert (await env.store.get_shot_plan(first.id)).visual_beats[0].image_status == 'approved'
    assert (await env.store.get_shot_plan(untouched.id)).model_dump() == untouched.model_dump()
    assert not env.gateway.calls
    assert all(t['spatial_reference_ids'] == [str(ref.id)] for t in state['targets'][:2])
    second_ref = await asset(env, '另一张空间样例')
    revision = state['revision_id']
    with pytest.raises(ProductionServiceError, match='确认替换'):
        await apply(env, second_ref, [untouched.visual_beats[0].id, first.visual_beats[0].id])
    assert str((await env.store.get_production_project(env.project.id)).current_revision_id) == revision
    assert not (await env.store.get_shot_plan(untouched.id)).image_prompt_mentions
    await apply(env, second_ref, targets, replace=True)
    assert await env.store.get_reference_asset(ref.id) is not None
    assert (await env.store.get_shot_plan(first.id)).visual_beats[0].approved_image_candidate_id == approved


@pytest.mark.asyncio
async def test_bulk_rejects_stale_foreign_and_guide_without_writes(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=1)
    ref = await asset(env)
    beat = env.shots[0].visual_beats[0]
    for values in ({'expected_revision_id': uuid4()}, {'expected_context_id': uuid4()}, {'visual_beat_ids': [uuid4()]}):
        with pytest.raises(ProductionServiceError):
            await apply(env, ref, [beat.id], **values)
    state = await env.service.get_composition(env.project.id)
    await env.service.update_composition(env.project.id, CompositionUpdate(expected_revision_id=state['revision_id'],
        expected_context_id=state['context_id'], visual_beat_ids=[beat.id], guide=CompositionGuide(x=.4, y=.2, width=.2, height=.6, aspect_ratio=9/16)))
    with pytest.raises(ProductionServiceError, match='构图引导'):
        await apply(env, ref, [beat.id])
    assert not (await env.store.get_shot_plan(env.shots[0].id)).image_prompt_mentions


@pytest.mark.asyncio
async def test_multi_beat_save_preserves_roles_and_other_beat_bindings(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=1, durable=True)
    ref = await asset(env)
    plan = env.shots[0]
    first = plan.visual_beats[0].model_copy(update={'end_ratio': .5, 'image_prompt_mentions': [
        PromptAssetMention(reference_asset_id=ref.id, label='样例', role='spatial')]})
    second = first.model_copy(update={'id': uuid4(), 'index': 2, 'start_ratio': .5, 'end_ratio': 1,
        'image_prompt_mentions': [PromptAssetMention(reference_asset_id=ref.id, label='样例', role='scene')]})
    plan = plan.model_copy(update={'visual_beats': [first, second]})
    await env.store.save_shot_plan(plan)
    await env.store.save_reference_binding(ReferenceBinding(shot_plan_id=plan.id, reference_asset_id=ref.id, role='scene'))
    await env.service.update_visual_beat(plan.id, first.id, ShotVisualBeatUpdate(
        expected_revision_id=env.project.current_revision_id, image_prompt=first.image_prompt,
        image_prompt_mentions=first.image_prompt_mentions,
        reference_bindings=[{'reference_asset_id': ref.id, 'role': 'scene'}]))
    saved = await env.store.get_shot_plan(plan.id)
    bindings = await env.store.list_reference_bindings(plan.id)
    assert env.service._image_bindings_for_beat(saved, saved.visual_beats[0], bindings)[0].role == 'spatial'
    assert env.service._image_bindings_for_beat(saved, saved.visual_beats[1], bindings)[0].role == 'scene'
    current = await env.store.get_production_project(env.project.id)
    await env.service.update_visual_beat(plan.id, first.id, ShotVisualBeatUpdate(
        expected_revision_id=current.current_revision_id, image_prompt_mentions=[], reference_bindings=[]))
    assert len(await env.store.list_reference_bindings(plan.id)) == 1
    from viral_dna_api.sqlite_store import SQLiteStore
    reloaded = SQLiteStore(env.workspace.database_path)
    assert (await reloaded.get_shot_plan(plan.id)).visual_beats[1].image_prompt_mentions[0].role == 'scene'


def test_video_auxiliary_images_do_not_become_timed_frames(tmp_path):
    from viral_dna_api.models import ShotPlan
    from viral_dna_api.video_generation.contracts import OrderedReferenceFrame
    from viral_dna_api.video_generation.gateway import _positive_prompt
    shot = ShotPlan(project_id=uuid4(), revision_id=uuid4(), source_shot_id='test', index=1,
                    start_seconds=0, end_seconds=3, duration_seconds=3, image_prompt='静态', video_prompt='向左行走')
    def frame(index, role):
        return OrderedReferenceFrame(visual_beat_id=uuid4(), candidate_id=uuid4(), ordinal=index,
            title=role, path=tmp_path/'test.png', relative_path='test.png', sha256='a'*64,
            start_ratio=0, end_ratio=1, transition_to_next_type='cut', transition_to_next_duration_seconds=0,
            role=role, source_kind='approved_frame' if role=='composition' else 'project_asset')
    prompt = _positive_prompt(shot, (frame(1, 'composition'), frame(2, 'spatial'), frame(3, 'style')))
    assert '图2（spatial）为辅助参考，不是视频首帧或时序关键帧' in prompt
    assert '图3（style）为辅助参考' in prompt
    assert '图1到图2' not in prompt and '图2到图3' not in prompt
    assert '已采用分镜图的空间关系优先' in prompt


def test_use_roles_override_binding_without_mutating_asset_or_other_beats():
    ref_id, plan_id = uuid4(), uuid4()
    binding = ReferenceBinding(shot_plan_id=plan_id, reference_asset_id=ref_id, role='scene')
    explicit = PromptAssetMention(reference_asset_id=ref_id, label='样例', role='spatial')
    legacy = PromptAssetMention(reference_asset_id=ref_id, label='样例')
    assert scoped_bindings([binding], [explicit])[0].role == 'spatial'
    assert scoped_bindings([binding], [legacy])[0].role == 'scene'
    assert binding.role == 'scene'
    assert 'role' not in legacy.model_dump()
    assert PromptAssetMention.model_validate(explicit.model_dump()).role == 'spatial'


def library_with_reference(tmp_path, monkeypatch):
    from viral_dna_api import style_library, style_reference
    library = StyleLibrary(tmp_path / 'styles.sqlite3')
    monkeypatch.setattr(style_library, 'get_style_library', lambda: library)
    monkeypatch.setattr(style_reference, 'get_style_library', lambda: library)
    return library, next(item for item in library.catalog()['items'] if item['name'] == '旅行 Vlog')


@pytest.mark.asyncio
async def test_batch_preflight_counts_dedicated_style_input(tmp_path, monkeypatch):
    from viral_dna_api.image_batches_models import ImageBatchRequest
    env = await environment(tmp_path, monkeypatch, count=1)
    library, style = library_with_reference(tmp_path, monkeypatch)
    plan = env.shots[0]
    cap = load_image_model_catalog().option('qwen_image_2_pro').capabilities
    limit = min(cap.max_reference_images, cap.max_input_images)
    mentions = []
    for index in range(limit):
        ref = await asset(env, f'普通参考{index}')
        mentions.append(PromptAssetMention(reference_asset_id=ref.id, label=ref.name, role='scene'))
        await env.store.save_reference_binding(ReferenceBinding(shot_plan_id=plan.id, reference_asset_id=ref.id, role='scene'))
    beat = plan.visual_beats[0].model_copy(update={'image_prompt_mentions': mentions})
    await env.store.save_shot_plan(plan.model_copy(update={'visual_beats': [beat]}))
    context = await env.service.get_prompt_context(env.project.id)
    request = ImageBatchRequest(expected_revision_id=env.project.current_revision_id)
    assert (await env.batch.preview(env.project.id, request)).items[0].status == 'pending'
    monkeypatch.setattr(env.service, 'get_prompt_context', AsyncMock(return_value=context.model_copy(update={
        'visual_style_snapshot': library.frozen(style['id'], style['version'])})))
    preview = await env.batch.preview(env.project.id, request)
    assert preview.items[0].status == 'failed'
    assert f'需要 {limit+1} 项参考' in preview.items[0].error_message
    assert not env.gateway.calls


def test_dedicated_style_reference_keeps_original_and_old_versions(tmp_path, monkeypatch):
    library, style = library_with_reference(tmp_path, monkeypatch)
    snapshot = library.frozen(style['id'], style['version'])
    assert snapshot['reference_image']['sha256'] == '30582569ddec6a6ddb3ea1054da3c57543ad90c2e9e572f0300f7d0c2954f628'
    assert 'reference_image' not in library.frozen(style['id'], 1)
    reopened = StyleLibrary(library.path)
    assert reopened.frozen(style['id'], style['version']) == snapshot
    assert next(item for item in reopened.catalog()['items'] if item['id'] == style['id'])['version'] == style['version']
    raw = io.BytesIO(); Image.new('RGB', (23, 17), 'blue').save(raw, format='PNG')
    media = library.upload(raw.getvalue(), purpose='reference')
    assert library.reference_content(media['id']) == raw.getvalue()
    with pytest.raises(HTTPException):
        library.media(media['id'])
    published = library.action(style['id'], library.save(style['id'], StyleWrite(expected_revision=style['revision'],
        style=StyleDefinition(**{**{key: style[key] for key in StyleDefinition.model_fields}, 'reference_image_id': media['id']})))['revision'], 'publish')
    assert published['version'] == 3
    assert library.frozen(style['id'], 2) == snapshot
    assert library.media(media['id']).media_type == 'image/png'


@pytest.mark.asyncio
@pytest.mark.parametrize('capacity', [0, 1])
async def test_actual_gateway_sends_style_bytes_and_counts_input_limit(tmp_path, monkeypatch, capacity):
    workspace, _, project, shot, _ = await prepare(tmp_path, monkeypatch)
    library, style = library_with_reference(tmp_path, monkeypatch)
    frozen = library.frozen(style['id'], style['version'])
    option = load_image_model_catalog().option('qwen_image_2_pro')
    identity = AdapterIdentity(execution_mode=ImageExecutionMode.REMOTE_API, provider=option.provider, model=option.model,
        model_snapshot=option.model, adapter_id='isolated', adapter_version='1', protocol_version='test',
        capability=option.capabilities.model_copy(update={'max_reference_images': capacity}), model_option=option,
        estimated_cost_micros=0, cost_estimate_known=True, cost_source=GenerationCostSource.CONFIGURED_RATE)
    adapter = SimpleNamespace(generate=AsyncMock(side_effect=RuntimeError('mock: never paid')))
    gateway = ImageGenerationGateway(workspace, SimpleNamespace(get=lambda: SimpleNamespace(enabled=True, execution_mode='remote_api', semantic_quality_enabled=False)))
    gateway._adapter = AsyncMock(return_value=(identity, adapter))
    with pytest.raises((RuntimeError, ImageGenerationGatewayError)):
        await gateway.generate(project, shot, project.current_revision_id, [], [], candidate_count=1, source_path=None,
                               input_mode='text_to_image', reuse_cache=False, visual_style_snapshot=frozen)
    if capacity == 0:
        adapter.generate.assert_not_called()
    else:
        request = adapter.generate.call_args.args[0]
        assert request.input_mode == 'reference_to_image'
        assert len(request.references) == 1 and request.references[0].role == 'style'
        assert hashlib.sha256(request.references[0].path.read_bytes()).hexdigest() == frozen['reference_image']['sha256']
        assert '不继承' in request.positive_prompt
        bad = {**frozen, 'reference_image': {**frozen['reference_image'], 'sha256': 'a'*64}}
        with pytest.raises(HTTPException):
            image_style_reference(workspace, bad, 'image')
