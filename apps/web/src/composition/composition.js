export function defaultComposition(ratio = 16 / 9) {
  return {version:1, aspect_ratio:ratio, x:0.4, y:0.18, width:0.2, height:0.65, subject_reference_id:null, subject_label:'主要人物', facing:'auto'};
}

export function clampBox(box) {
  const width = Math.max(0.03, Math.min(1, Number(box.width) || 0.03));
  const height = Math.max(0.05, Math.min(1, Number(box.height) || 0.05));
  return {...box, width, height, x:Math.max(0, Math.min(1-width, Number(box.x) || 0)), y:Math.max(0, Math.min(1-height, Number(box.y) || 0))};
}

export function effectiveComposition(state, projectId, beatId) {
  const entries = state?.entries || {};
  return Object.hasOwn(entries, beatId) ? entries[beatId] : entries['default:'+projectId] || null;
}

export function moveBox(box, dx, dy, resize = false) {
  return clampBox(resize ? {...box, width:Math.min(1-box.x,box.width+dx), height:Math.min(1-box.y,box.height+dy)} : {...box,x:box.x+dx,y:box.y+dy});
}

export function compositionDifference(target, actual) {
  return {horizontal:((actual.x+actual.width/2)-(target.x+target.width/2))*100,
    feet:((actual.y+actual.height)-(target.y+target.height))*100, height:(actual.height-target.height)*100};
}

// Mirrors the server's integer geometry. Source boxes are human measurements.
export function reframeGeometry(source, target, sourceWidth, sourceHeight, width, height) {
  if (![sourceWidth,sourceHeight,width,height,source.height].every(value=>Number.isFinite(value)&&value>0)) return {error:'原图尺寸不可用，请重新选择图片'};
  const factor=height*target.height/(sourceHeight*source.height);
  const scaledWidth=Math.round(sourceWidth*factor), scaledHeight=Math.round(sourceHeight*factor);
  const left=Math.round(width*(target.x+target.width/2)-scaledWidth*(source.x+source.width/2));
  const top=Math.round(height*target.y-scaledHeight*source.y);
  const actual={x:(left+scaledWidth*source.x)/width,y:(top+scaledHeight*source.y)/height,width:scaledWidth*source.width/width,height:scaledHeight*source.height/height};
  const error=scaledWidth>=width&&scaledHeight>=height?'请减小目标人物高度，留出待扩图区域':left<0||top<0||left+scaledWidth>width||top+scaledHeight>height?'目标位置会裁掉原图，请减小人物高度或向中心移动':'';
  return {left,top,scaledWidth,scaledHeight,actual,error};
}
