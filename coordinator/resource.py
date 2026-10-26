"""Resource and hardware monitoring utilities (GPU, VRAM, and process tracking)."""

import subprocess
import shutil
import time
from typing import Dict, Any, List, Optional, Callable


def is_nvidia_gpu_available() -> bool:
    """Check if nvidia-smi is installed and accessible."""
    return shutil.which("nvidia-smi") is not None


def get_gpu_status() -> Dict[str, Any]:
    """
    Query NVIDIA GPU information using nvidia-smi.
    Returns free memory in MB, total memory, utilization, and running compute processes.
    """
    if not is_nvidia_gpu_available():
        return {
            "available": False,
            "error": "nvidia-smi not available",
            "gpus": [],
            "compute_apps": [],
        }

    gpus = []
    try:
        res = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.free,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode == 0:
            for line in res.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 5:
                    gpus.append({
                        "index": int(parts[0]),
                        "name": parts[1],
                        "total_mb": float(parts[2]),
                        "free_mb": float(parts[3]),
                        "utilization_pct": float(parts[4]),
                    })
    except Exception as e:
        return {"available": False, "error": str(e), "gpus": [], "compute_apps": []}

    compute_apps = []
    try:
        app_res = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if app_res.returncode == 0:
            for line in app_res.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    compute_apps.append({
                        "pid": int(parts[0]),
                        "process_name": parts[1],
                        "used_mb": float(parts[2]),
                    })
    except Exception:
        pass

    return {
        "available": True,
        "gpus": gpus,
        "compute_apps": compute_apps,
        "total_free_mb": sum(g["free_mb"] for g in gpus) if gpus else 0,
    }


def wait_for_gpu(
    min_free_mb: int = 1500,
    poll_interval: int = 10,
    max_wait_seconds: Optional[int] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Wait until the GPU has at least min_free_mb free VRAM and no competing compute processes.
    Costs 0 LLM tokens.
    """
    if not is_nvidia_gpu_available():
        if log_fn:
            log_fn("No NVIDIA GPU detected; proceeding without GPU wait.")
        return True

    start_time = time.time()
    while True:
        status = get_gpu_status()
        if not status.get("available"):
            return True

        gpus = status.get("gpus", [])
        compute_apps = status.get("compute_apps", [])
        total_free = status.get("total_free_mb", 0)

        # Check if condition met
        if total_free >= min_free_mb and len(compute_apps) == 0:
            if log_fn:
                log_fn(f"✅ GPU ready: {total_free:.0f}MB free VRAM, 0 compute processes.")
            return True

        elapsed = time.time() - start_time
        if max_wait_seconds and elapsed >= max_wait_seconds:
            if log_fn:
                log_fn(f"⚠️ GPU wait timed out after {elapsed:.0f}s. Proceeding anyway.")
            return False

        if log_fn:
            app_desc = f"{len(compute_apps)} compute processes" if compute_apps else "no compute apps"
            log_fn(
                f"⏳ Waiting for GPU: currently {total_free:.0f}MB free (need {min_free_mb}MB), "
                f"{app_desc}. Checking again in {poll_interval}s (elapsed: {int(elapsed)}s)..."
            )

        time.sleep(poll_interval)
