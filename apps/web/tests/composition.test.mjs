import assert from 'node:assert/strict';
import test from 'node:test';
import {clampBox, compositionDifference, defaultComposition, effectiveComposition, moveBox} from '../src/composition/composition.js';
import {createGlobalPromptSession} from '../src/prompt-context/global-prompt-session.js';

test('normalized position, scale and presets stay on canvas',()=>{
  const box=defaultComposition();
  assert.equal(moveBox(box,2,2).x,.8);
  assert.equal(moveBox(box,-2,-2).y,0);
  assert.equal(moveBox(box,2,2,true).width,.6);
  assert.equal(clampBox({...box,width:0}).width,.03);
});
test('per-frame disable is distinct from default inheritance',()=>{
  const guide=defaultComposition(), state={entries:{'default:p':guide,a:null,b:{...guide,x:.1}}};
  assert.equal(effectiveComposition(state,'p','a'),null);
  assert.equal(effectiveComposition(state,'p','b').x,.1);
  assert.equal(effectiveComposition(state,'p','c'),guide);
  assert.equal(effectiveComposition(state,'q','c'),null);
});
test('manual comparison measures trunk, foot line and size, without claiming automatic detection',()=>{
  const guide=defaultComposition();
  const delta=compositionDifference(guide,{...guide,x:guide.x+.1,y:guide.y+.02});
  assert.ok(Math.abs(delta.horizontal-10)<.001);
  assert.ok(Math.abs(delta.feet-2)<.001);
  assert.equal(delta.height,0);
});
test('refresh after composition save cannot erase unsaved global text',()=>{
  const initial={id:'old',common_image_prompt:'自然光',common_video_prompt:''};
  const session=createGlobalPromptSession(initial,{save:async()=>initial});
  assert.equal(session.acceptRevision({...initial,id:'new'}),true);
  session.edit('image','手写草稿');
  assert.equal(session.acceptRevision({...initial,id:'other'}),false);
  assert.equal(session.snapshot().values.common_image_prompt,'手写草稿');
});
