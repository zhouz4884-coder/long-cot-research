from pathlib import Path
from modelscope import snapshot_download
root=Path('/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9')
path=snapshot_download('Qwen/Qwen3-4B-Thinking-2507',local_dir=str(root/'models/Qwen3-4B-Thinking-2507'),cache_dir=str(root/'cache/modelscope-reason-transition'))
print(path,flush=True)
