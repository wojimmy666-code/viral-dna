from asyncio import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_asset_library_api import _test_client, _upload
from test_image_batches import environment, finish
from test_prompt_documents import fixture
from test_prompt_engine import PromptRepository, build_report
from test_storyboard_prompt_editor import runtime
from test_upstream_changes import adopt
from test_video_groups import setup_group

from viral_dna_api.image_batches_models import ImageBatchRequest
from viral_dna_api.models import ShotPlanCreate, ProductionStep, ReferenceAsset, ShotVideoGenerationDraft, VideoGenerationCreate, VideoPromptMention
from viral_dna_api.production import ProductionServiceError
from viral_dna_api.production_prompt_documents import ProductionPromptDocuments, PromptDocumentUpdate, document_bodies
from viral_dna_api.project_prompts import ProjectPromptUpdate, prompt_snapshot
from viral_dna_api.prompt_engine.contracts import PromptDraftUpdateRequest, PromptShotDraftUpdate, SourcePromptAssetMention
from viral_dna_api.prompt_engine.service import PromptDraftService, PromptDraftServiceError
from viral_dna_api.skill_workflow.service import SkillWorkflowServiceError
from viral_dna_api.video_group_models import GroupAssetMention, VideoGenerationGroup, VideoGroupUpdate
from viral_dna_api.video_generation.catalog import load_video_model_catalog


def reference(project, name='旅行背包'):
    return ReferenceAsset(project_id=project, name=name, type='prop', relative_path='references/example.png',
                          mime_type='image/png', width=320, height=240, sha256='a' * 64, rights_confirmed=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('durable', [False, True])
async def test_global_assets_survive_reload_and_reach_image_gateway_without_local_mutation(tmp_path, monkeypatch, durable):
    env = await environment(tmp_path, monkeypatch, count=1, durable=durable)
    asset = reference(env.project.id)
    await env.store.save_reference_asset(asset)
    context = await env.service.get_prompt_context(env.project.id)
    saved = await env.service.update_prompt_context(env.project.id, ProjectPromptUpdate(
        expected_revision_id=context.id, common_image_prompt=f'所有分镜保留 @{asset.name}', common_video_prompt='',
        common_image_mentions=[{'reference_asset_id': asset.id, 'label': asset.name}],
    ))
    assert (await env.service.get_prompt_context(env.project.id)).common_image_mentions == saved.common_image_mentions
    captured = []
    generate = env.gateway.generate
    async def capture(project, shot, revision, bindings, assets, **options):
        captured.append((shot, bindings, options))
        return await generate(project, shot, revision, bindings, assets, **options)
    env.gateway.generate = capture
    env.gateway.release.set()
    batch = await env.batch.create(env.project.id, ImageBatchRequest(expected_revision_id=env.project.current_revision_id))
    result = await finish(env, batch)
    assert result.status == 'completed'
    shot, bindings, options = captured[0]
    assert [item.reference_asset_id for item in bindings] == [asset.id]
    assert shot.image_prompt_mentions[0].reference_asset_id == asset.id
    assert f'@{asset.name}' in shot.image_prompt
    assert options['input_mode'] == 'reference_to_image'
    assert (await env.store.get_shot_plan(env.shots[0].id)).image_prompt_mentions == []
    assert await env.store.list_reference_bindings(env.shots[0].id) == []


@pytest.mark.asyncio
async def test_global_reference_scope_validation_and_clear(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=1)
    context = await env.service.get_prompt_context(env.project.id)
    payload = dict(expected_revision_id=context.id, common_image_prompt='@不属于本项目', common_video_prompt='',
                   common_image_mentions=[{'reference_asset_id': uuid4(), 'label': '不属于本项目'}])
    with pytest.raises(ProductionServiceError):
        await env.service.update_prompt_context(env.project.id, ProjectPromptUpdate(**payload))
    assert (await env.service.get_prompt_context(env.project.id)).id == context.id
    asset = reference(env.project.id)
    await env.store.save_reference_asset(asset)
    saved = await env.service.update_prompt_context(env.project.id, ProjectPromptUpdate(**(payload | {
        'common_image_prompt': f'@{asset.name}', 'common_image_mentions': [{'reference_asset_id': asset.id, 'label': asset.name}],
    })))
    cleared = await env.service.update_prompt_context(env.project.id, ProjectPromptUpdate(
        expected_revision_id=saved.id, common_image_prompt='普通画面', common_video_prompt='', common_image_mentions=[]))
    assert cleared.common_image_mentions == []


@pytest.mark.asyncio
@pytest.mark.parametrize('durable', [False, True])
async def test_document_saves_real_image_and_video_bindings_atomically(tmp_path, monkeypatch, durable):
    monkeypatch.setenv('VIRAL_DNA_WORKSPACE_ROOT', str(tmp_path))
    repo, _, _, production, _, result = await fixture(tmp_path, durable)
    asset = reference(result.project_id)
    await repo.save_reference_asset(asset)
    plans = await repo.list_shot_plans(result.project_id)
    draft = ShotVideoGenerationDraft(project_id=result.project_id, shot_plan_id=plans[0].id,
                                    model_alias='seedance', resolution='720P', duration_seconds=5,
                                    video_prompt=plans[0].video_prompt)
    assert await repo.compare_and_swap_video_generation_draft(draft, 0)
    documents = ProductionPromptDocuments(production)
    before = await documents.get(result.project_id)
    body = document_bodies(before)
    image = body['shots'][0]['images'][0]
    image['prompt'] += f' @{asset.name}'
    image['mentions'] = [{'reference_asset_id': str(asset.id), 'label': asset.name}]
    row = body['shots'][0]
    row['video_prompt'] += f' @资产/{asset.name}'
    row['video_mentions'] = [VideoPromptMention(reference_kind='project_asset', reference_id=asset.id,
                                               label=f'资产/{asset.name}', role='composition').model_dump(mode='json')]
    saved = await documents.save(result.project_id, PromptDocumentUpdate(expected_token=before['token'], **body))
    assert saved['shots'][0]['images'][0]['mentions'][0]['reference_asset_id'] == str(asset.id)
    bindings = await repo.list_reference_bindings(plans[0].id)
    assert [item.reference_asset_id for item in bindings] == [asset.id]
    video = await repo.get_video_generation_draft(plans[0].id)
    assert video.input_plan.references[0].reference_id == asset.id
    assert 'project_assets' in video.input_plan.sources
    assert video.draft_version == draft.draft_version + 1
    invalid = document_bodies(saved)
    invalid['shots'][1]['images'][0]['mentions'] = [{'reference_asset_id': str(uuid4()), 'label': '外部资产'}]
    invalid['shots'][1]['images'][0]['prompt'] += ' @外部资产'
    with pytest.raises(ProductionServiceError):
        await documents.save(result.project_id, PromptDocumentUpdate(expected_token=saved['token'], **invalid))
    assert (await documents.get(result.project_id))['token'] == saved['token']


def test_picker_image_filter_precedes_pagination(tmp_path, monkeypatch):
    client, workspace_id, _ = _test_client(tmp_path, monkeypatch)
    for name, kind in [('杯子', 'product'), ('品牌标志', 'logo'), ('衣服', 'clothing')]:
        assert _upload(client, workspace_id, name=name, asset_type=kind, folder_id=None, color=(30, 40, 50)).status_code == 201
    first = client.get(f'/api/v1/workspaces/{workspace_id}/assets?prompt_images_only=true&page_size=1').json()
    assert first['total'] == 2 and first['total_pages'] == 2
    assert first['items'][0]['type'] != 'logo'
    assert client.get(f'/api/v1/workspaces/{workspace_id}/assets').json()['total'] == 3


def test_group_legacy_fingerprint_shape_and_reference_metadata():
    group = VideoGenerationGroup(shot_plan_ids=[uuid4(), uuid4()])
    assert 'video_prompt_mentions' not in group.model_dump(mode='json')
    enriched = group.model_copy(update={'video_prompt': '保留 @背包'})
    assert enriched.video_prompt_mentions == []


@pytest.mark.asyncio
async def test_new_shot_keeps_references_on_its_visual_beat(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=1)
    asset = reference(env.project.id)
    await env.store.save_reference_asset(asset)
    await env.service.create_shot(env.project.id, ShotPlanCreate(
        expected_revision_id=env.project.current_revision_id, mode='blank', image_prompt=f'@{asset.name} 在画面中',
        image_prompt_mentions=[{'reference_asset_id': asset.id, 'label': asset.name}],
    ))
    added = next(item for item in await env.store.list_shot_plans(env.project.id) if item.id != env.shots[0].id)
    assert added.image_prompt_mentions[0].reference_asset_id == asset.id
    assert added.visual_beats[0].image_prompt_mentions == added.image_prompt_mentions
    assert (await env.store.list_reference_bindings(added.id))[0].reference_asset_id == asset.id


@pytest.mark.asyncio
async def test_group_mentions_and_globals_are_real_inputs_and_change_the_fingerprint(tmp_path, monkeypatch):
    env, service, group, before = await setup_group(tmp_path, monkeypatch)
    asset = reference(env.project.id)
    await env.store.save_reference_asset(asset)
    mention = GroupAssetMention(reference_id=asset.id, label=asset.name, role='composition')
    project = await env.store.get_production_project(env.project.id)
    enriched = group.model_copy(update={'video_prompt': f'每段都保留 @{asset.name}', 'video_prompt_mentions': [mention]})
    saved = await service.update(project.id, VideoGroupUpdate(expected_revision_id=project.current_revision_id, groups=[enriched]))
    row = saved['groups'][0]
    assert row['input_plan']['references'][-1]['reference_id'] == str(asset.id)
    assert row['input_fingerprint'] != before['groups'][0]['input_fingerprint']
    context = await env.service.get_prompt_context(project.id)
    await env.service.update_prompt_context(project.id, ProjectPromptUpdate(
        expected_revision_id=context.id, common_image_prompt='', common_video_prompt=f'全片 @{asset.name}',
        common_video_mentions=[VideoPromptMention(reference_kind='project_asset', reference_id=asset.id, label=asset.name, role='composition')]))
    latest = (await service.state(project.id))['groups'][0]
    assert latest['input_fingerprint'] != row['input_fingerprint']
    assert len([ref for ref in latest['input_plan']['references'] if ref['reference_id'] == str(asset.id)]) == 1


@pytest.mark.asyncio
async def test_global_video_assets_merge_before_capability_validation_and_reach_gateway(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch, count=1)
    project = env.project.model_copy(update={'active_step': ProductionStep.SHOT_VIDEOS})
    await env.store.save_production_project(project)
    _, image, image_path = await adopt(env, env.shots[0])
    _, video, _ = await adopt(env, await env.store.get_shot_plan(env.shots[0].id), 'video')
    plan = await env.store.get_shot_plan(env.shots[0].id)
    plan = plan.model_copy(update={'video_prompt':'人物自然向左走'})
    await env.store.save_shot_plan(plan)
    run = await env.store.get_generation_run(video.generation_run_id)
    asset = reference(project.id)
    await env.store.save_reference_asset(asset)
    env.service.project_assets = SimpleNamespace(
        list_references=AsyncMock(return_value=[asset]), get_reference=AsyncMock(return_value=asset),
        resolve_content=AsyncMock(return_value=(image_path, 'image/png')),
        snapshot_reference=AsyncMock(return_value=asset.model_dump(mode='json')),
    )
    context = await env.service.get_prompt_context(project.id)
    context = await env.service.update_prompt_context(project.id, ProjectPromptUpdate(
        expected_revision_id=context.id, common_image_prompt='', common_video_prompt=f'全片使用 @{asset.name}',
        common_video_mentions=[VideoPromptMention(reference_kind='project_asset', reference_id=asset.id, label=asset.name, role='composition')]))
    frozen = prompt_snapshot(plan.video_prompt, context, 'video')
    payload = VideoGenerationCreate(expected_revision_id=project.current_revision_id,
        input_plan={'sources':['approved_images'], 'references':[{'reference_kind':'approved_image','reference_id':image.id,'label':'图1','role':'composition','order':1}]}, audio_strategy='muted')
    cap = load_video_model_catalog().option('minimax_h3').capability
    captured = []
    class StopAfterValidation(Exception):
        pass
    async def validate(project_arg, plan_arg, incoming, capability):
        captured.append(incoming)
        raise StopAfterValidation
    monkeypatch.setattr(env.service, '_validate_video_input_plan', validate)
    env.service.video_gateway = SimpleNamespace(resolve_identity=lambda **_: (SimpleNamespace(capability=cap), None))
    with pytest.raises(StopAfterValidation):
        await env.service._enqueue_video_run(plan.id, payload)
    merged = captured[0]
    assert merged.input_plan.references[-1].reference_id == asset.id
    assert 'project_assets' in merged.input_plan.sources
    async def generate(project_arg, execution_plan, revision, references, **options):
        assert execution_plan.video_prompt_mentions[-1].reference_id == asset.id
        assert f'@{asset.name}' in execution_plan.video_prompt
        assert references[-1].candidate_id == asset.id
        assert references[-1].source_kind == 'project_asset'
        return run, [video]
    env.service.video_gateway.generate = generate
    monkeypatch.setattr(env.service, '_validate_video_input_plan', AsyncMock())
    queued = run.model_copy(update={'request_payload': merged.model_dump(mode='json') | {'prompt_snapshot': frozen}})
    await env.service._execute_video_run_request(plan.id, merged, run_id=run.id, cancellation=Event(), queued_run=queued)


@pytest.mark.asyncio
async def test_skill_global_assets_require_current_project_selection():
    env = await runtime()
    asset_id = uuid4()
    env.service.prompt_assets = AsyncMock(return_value=[{'asset_id':str(asset_id),'image_eligible':True}])
    context = await env.service.get_prompt_context(env.project.id)
    saved = await env.service.update_prompt_context(env.project.id, ProjectPromptUpdate(
        expected_revision_id=context.id, common_image_prompt='@服装', common_video_prompt='',
        common_image_mentions=[{'reference_asset_id':asset_id,'label':'服装'}]))
    assert saved.common_image_mentions[0].reference_asset_id == asset_id
    with pytest.raises(SkillWorkflowServiceError):
        await env.service.update_prompt_context(env.project.id, ProjectPromptUpdate(
            expected_revision_id=saved.id, common_image_prompt='@他人资产', common_video_prompt='',
            common_image_mentions=[{'reference_asset_id':uuid4(),'label':'他人资产'}]))


@pytest.mark.asyncio
async def test_original_prompt_document_validates_and_retains_asset_metadata():
    repo = PromptRepository(build_report())
    asset = reference(uuid4(), name='人物/betty')
    library = SimpleNamespace(get_asset=AsyncMock(return_value=SimpleNamespace(**asset.model_dump(), media_kind='image')))
    service = PromptDraftService(repo, asset_library=library)
    original = await service.get_package(repo.report.analysis_id)
    draft = original.shots[0].draft.model_copy(deep=True)
    draft.visual.subjects += f' @{asset.name}'
    draft.asset_mentions = [SourcePromptAssetMention(reference_asset_id=asset.id,label=asset.name)]
    saved = await service.update_package(repo.report.analysis_id, PromptDraftUpdateRequest(expected_revision_id=original.revision_id, shots=[PromptShotDraftUpdate(shot_id=original.shots[0].shot_id,draft=draft)]))
    assert saved.shots[0].draft.asset_mentions == draft.asset_mentions
    library.get_asset.return_value.rights_confirmed = False
    with pytest.raises(PromptDraftServiceError):
        await service.update_package(repo.report.analysis_id, PromptDraftUpdateRequest(expected_revision_id=saved.revision_id,shots=[PromptShotDraftUpdate(shot_id=original.shots[0].shot_id,draft=draft)]))
