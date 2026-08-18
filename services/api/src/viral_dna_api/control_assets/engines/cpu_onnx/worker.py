from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image


def _read_exact(stream, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _robust_normalize(depth: np.ndarray) -> np.ndarray:
    low, high = np.percentile(depth, (2.0, 98.0))
    if high <= low + 1e-6:
        return np.zeros_like(depth, dtype=np.float32)
    return np.clip((depth - low) / (high - low), 0.0, 1.0).astype(np.float32)


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description="ViralDNA CPU depth video worker")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--thumbnail", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--fps", type=float, required=True)
    parser.add_argument("--frames", type=int, required=True)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.thumbnail.parent.mkdir(parents=True, exist_ok=True)

    session_options = ort.SessionOptions()
    session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session_options.intra_op_num_threads = 0
    session_options.inter_op_num_threads = 1
    session = ort.InferenceSession(
        str(args.model),
        sess_options=session_options,
        providers=["CPUExecutionProvider"],
    )
    input_name = session.get_inputs()[0].name
    print("model=ready provider=CPUExecutionProvider", flush=True)

    decoder_command = [
        args.ffmpeg,
        "-v",
        "error",
        "-ss",
        f"{args.start:.6f}",
        "-t",
        f"{args.duration:.6f}",
        "-i",
        str(args.source),
        "-map",
        "0:v:0",
        "-vf",
        f"fps={args.fps:.8f},scale={args.width}:{args.height}:flags=lanczos",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "pipe:1",
    ]
    encoder_command = [
        args.ffmpeg,
        "-y",
        "-v",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-s",
        f"{args.width}x{args.height}",
        "-r",
        f"{args.fps:.8f}",
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(args.output),
    ]

    decoder = subprocess.Popen(decoder_command, stdout=subprocess.PIPE)
    encoder = subprocess.Popen(encoder_command, stdin=subprocess.PIPE)
    if decoder.stdout is None or encoder.stdin is None:
        _terminate(decoder)
        _terminate(encoder)
        raise RuntimeError("无法建立 FFmpeg 深度视频管道")

    frame_size = args.width * args.height * 3
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)[:, None, None]
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)[:, None, None]
    previous_depth: np.ndarray | None = None
    processed = 0
    started = time.perf_counter()

    try:
        while True:
            raw = _read_exact(decoder.stdout, frame_size)
            if len(raw) != frame_size:
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(
                args.height, args.width, 3
            )
            resized = Image.fromarray(frame, "RGB").resize(
                (518, 518), Image.Resampling.BICUBIC
            )
            tensor = np.asarray(resized, dtype=np.float32) / 255.0
            tensor = (tensor.transpose(2, 0, 1) - mean) / std
            tensor = tensor[None].astype(np.float32, copy=False)

            depth = np.squeeze(session.run(None, {input_name: tensor})[0]).astype(
                np.float32
            )
            depth = _robust_normalize(depth)
            if previous_depth is not None:
                scene_change = float(np.mean(np.abs(depth - previous_depth)))
                if scene_change < 0.22:
                    depth = 0.85 * depth + 0.15 * previous_depth
            previous_depth = depth

            depth_u8 = np.clip(depth * 255.0, 0, 255).astype(np.uint8)
            full_size = Image.fromarray(depth_u8, "L").resize(
                (args.width, args.height), Image.Resampling.BICUBIC
            )
            if processed == 0:
                full_size.save(args.thumbnail)
            encoder.stdin.write(np.asarray(full_size, dtype=np.uint8).tobytes())
            processed += 1

            elapsed = time.perf_counter() - started
            eta = (elapsed / processed) * max(args.frames - processed, 0)
            print(
                f"frames={processed}/{args.frames} elapsed={elapsed:.1f}s eta={eta:.1f}s",
                flush=True,
            )
    finally:
        decoder.stdout.close()
        decoder_returncode = decoder.wait()
        encoder.stdin.close()
        encoder_returncode = encoder.wait()

    if processed == 0:
        raise RuntimeError("没有从原视频解码出任何画面")
    if decoder_returncode != 0:
        raise RuntimeError(f"FFmpeg 解码失败：{decoder_returncode}")
    if encoder_returncode != 0:
        raise RuntimeError(f"FFmpeg 编码失败：{encoder_returncode}")
    print(f"completed frames={processed}", flush=True)


if __name__ == "__main__":
    main()
