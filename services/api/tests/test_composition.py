from io import BytesIO
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from pydantic import ValidationError
from test_image_batches import environment, finish
from test_image_input_modes import prepare

from viral_dna_api.composition import CompositionGuide, CompositionUpdate, effective_composition, guide_png
from viral_dna_api.image_batches_models import ImageBatchRequest
from viral_dna_api.models import ImageGenerationCreate, ImageExecutionMode, GenerationCostSource
from viral_dna_api.production import ProductionServiceError
from viral_dna_api.project_prompts import ProjectPromptUpdate
from viral_dna_api.image_generation.gateway import ImageGenerationGateway, ImageGenerationGatewayError
from viral_dna_api.image_generation.catalog import load_image_model_catalog
from viral_dna_api.image_generation.contracts import AdapterIdentity


def guide(project, **values):
    return CompositionGuide(aspect_ratio=project.output_width/project.output_height, x=.4, y=.2, width=.2, height=.6, **values)


async def save(service, project, guide_value=None, **options):
    current = await service.get_composition(project.id)
    return await service.update_composition(project.id, CompositionUpdate(
        expected_context_id=current['context_id'], expected_revision_id=current['revision_id'], guide=guide_value, **options))


@pytest.mark.parametrize('values', [{'x':.95}, {'height':.95}, {'width':0}, {'x':float('nan')}, {'facing':'pose_locked'}])
def test_invalid_geometry_is_rejected(values):
    with pytest.raises(ValidationError):
        CompositionGuide(**({'aspect_ratio':16/9,'x':.4,'y':.2,'width':.2,'height':.6}|values))


@pytest.mark.asyncio
@pytest.mark.parametrize('durable',[False, True])
async def test_defaults_overrides_disable_and_reload_preserve_prompts_and_history(tmp_path,monkeypatch,durable):
    env=await environment(tmp_path,monkeypatch,count=2,durable=durable)
    first,second=[shot.visual_beats[0].id for shot in env.shots]
    before=[shot.model_dump() for shot in env.shots]
    g=guide(env.project)
    default=await save(env.service,env.project,g,operation='default')
    await save(env.service,env.project,g.model_copy(update={'x':.2}),operation='apply',visual_beat_ids=[first])
    context=await env.service.get_prompt_context(env.project.id)
    assert effective_composition(context,env.project.id,first).x==.2
    assert effective_composition(context,env.project.id,second).x==.4
    await save(env.service,env.project,operation='disable',visual_beat_ids=[first])
    context=await env.service.get_prompt_context(env.project.id)
    assert effective_composition(context,env.project.id,first) is None
    await save(env.service,env.project,operation='inherit',visual_beat_ids=[first])
    context=await env.service.get_prompt_context(env.project.id)
    assert effective_composition(context,env.project.id,first)==g
    saved=await env.service.update_prompt_context(env.project.id,ProjectPromptUpdate(expected_revision_id=context.id,common_image_prompt='新的自然光',common_video_prompt=''))
    assert saved.image_compositions==context.image_compositions
    assert [item.model_dump() for item in await env.store.list_shot_plans(env.project.id)]==before
    assert default['revision_id']==str(env.project.current_revision_id)


@pytest.mark.asyncio
async def test_atomic_scope_revision_and_aspect_validation(tmp_path,monkeypatch):
    env=await environment(tmp_path,monkeypatch,count=1)
    state=await env.service.get_composition(env.project.id)
    common=dict(expected_context_id=state['context_id'],expected_revision_id=state['revision_id'],guide=guide(env.project))
    for extra in [dict(visual_beat_ids=[uuid4()]),dict(visual_beat_ids=[env.shots[0].visual_beats[0].id],expected_context_id=uuid4()),
                  dict(operation='default',guide=guide(env.project).model_copy(update={'aspect_ratio':16/9})),
                  dict(operation='default',guide=guide(env.project,subject_reference_id=uuid4()))]:
        with pytest.raises(ProductionServiceError):
            await env.service.update_composition(env.project.id,CompositionUpdate(**(common|extra)))
        assert (await env.service.get_composition(env.project.id))['context_id']==state['context_id']


@pytest.mark.asyncio
async def test_analysis_queue_freezes_guide_and_does_not_require_a_base(tmp_path,monkeypatch):
    _,repo,project,shot,service=await prepare(tmp_path,monkeypatch)
    g=guide(project)
    await save(service,project,g,operation='apply',visual_beat_ids=[shot.visual_beats[0].id])
    run=await service._enqueue_image_run(shot.id,ImageGenerationCreate(expected_revision_id=project.current_revision_id,input_mode='text_to_image'))
    frozen=run.request_payload['prompt_snapshot']
    assert frozen['composition_guide']==g.model_dump(mode='json')
    assert run.input_mode=='reference_to_image'
    await save(service,project,operation='disable',visual_beat_ids=[shot.visual_beats[0].id])
    assert (await repo.get_generation_run(run.id)).request_payload['prompt_snapshot']==frozen


@pytest.mark.asyncio
async def test_skill_batch_passes_each_effective_guide_to_gateway(tmp_path,monkeypatch):
    env=await environment(tmp_path,monkeypatch,count=2)
    g=guide(env.project)
    await save(env.service,env.project,g,operation='default')
    await save(env.service,env.project,None,operation='disable',visual_beat_ids=[env.shots[1].visual_beats[0].id])
    captured={}
    generate=env.gateway.generate
    async def capture(project,shot,*args,**options):
        captured[shot.id]=shot.image_composition
        return await generate(project,shot,*args,**options)
    env.gateway.generate=capture
    env.gateway.release.set()
    batch=await env.batch.create(env.project.id,ImageBatchRequest(expected_revision_id=env.project.current_revision_id))
    assert (await finish(env,batch)).status=='completed'
    assert captured[env.shots[0].id]==g.model_dump(mode='json')
    assert captured[env.shots[1].id] is None


def test_layout_diagram_is_deterministic_and_inside_requested_rectangle():
    g=CompositionGuide(aspect_ratio=16/9,x=.4,y=.2,width=.2,height=.6)
    content=guide_png(g,1920,1080)
    assert content==guide_png(g,1920,1080)
    image=Image.open(BytesIO(content))
    assert image.size==(1024,576)
    assert image.getpixel((0,0))==(255,255,255)
    assert image.getpixel((512,135))!=(255,255,255)


@pytest.mark.asyncio
@pytest.mark.parametrize('unsupported',[False,True])
async def test_real_gateway_passes_diagram_to_adapter_and_enforces_reference_cap(tmp_path,monkeypatch,unsupported):
    workspace,_,project,shot,_=await prepare(tmp_path,monkeypatch)
    option=load_image_model_catalog().option('qwen_image_2_pro')
    cap=option.capabilities.model_copy(update={'max_reference_images':0}) if unsupported else option.capabilities
    identity=AdapterIdentity(execution_mode=ImageExecutionMode.REMOTE_API,provider=option.provider,model=option.model,model_snapshot=option.model,
        adapter_id='test',adapter_version='1',protocol_version='test',capability=cap,model_option=option,
        estimated_cost_micros=0,cost_estimate_known=True,cost_source=GenerationCostSource.CONFIGURED_RATE)
    adapter=SimpleNamespace(generate=AsyncMock(side_effect=RuntimeError('stopped before paid generation')))
    gateway=ImageGenerationGateway(workspace,SimpleNamespace(get=lambda:SimpleNamespace(enabled=True,execution_mode='remote_api',semantic_quality_enabled=False)))
    gateway._adapter=AsyncMock(return_value=(identity,adapter))
    frozen=shot.model_copy(update={'image_composition':guide(project).model_dump(mode='json')})
    if unsupported:
        with pytest.raises(ImageGenerationGatewayError,match='参考图'):
            await gateway.generate(project,frozen,project.current_revision_id,[],[],candidate_count=1,source_path=None,input_mode='text_to_image',reuse_cache=False)
        adapter.generate.assert_not_called()
    else:
        with pytest.raises(RuntimeError,match='stopped before'):
            await gateway.generate(project,frozen,project.current_revision_id,[],[],candidate_count=1,source_path=None,input_mode='text_to_image',reuse_cache=False)
        request=adapter.generate.call_args.args[0]
        assert request.input_mode=='reference_to_image'
        assert len(request.references)==1
        assert request.references[0].role=='layout'
        assert request.references[0].path.is_file()
        assert '构图示意' in request.positive_prompt
        assert '50.0%' in request.positive_prompt
