export function uploadFormWithProgress(url, body, onProgress, signal, errorMessage) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const abort = () => xhr.abort();
    const cleanup = () => signal?.removeEventListener("abort", abort);
    xhr.open("POST", url);
    xhr.responseType = "json";
    xhr.upload.onprogress = event => onProgress?.(event.lengthComputable ? Math.round(event.loaded / event.total * 100) : null);
    xhr.onload = () => {
      cleanup();
      if (xhr.status >= 200 && xhr.status < 300) { resolve(xhr.response); return; }
      const error = new Error(errorMessage(xhr.response, xhr.status));
      error.status = xhr.status;
      reject(error);
    };
    xhr.onerror = () => { cleanup(); reject(new Error("上传连接中断，请重试；旧封面未改变")); };
    xhr.onabort = () => { cleanup(); reject(new DOMException("上传已取消", "AbortError")); };
    if (signal?.aborted) { reject(new DOMException("上传已取消", "AbortError")); return; }
    signal?.addEventListener("abort", abort, { once: true });
    xhr.send(body);
  });
}
