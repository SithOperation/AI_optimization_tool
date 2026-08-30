"""Tiny dependency-free TokenScope event client."""
import json
from urllib.request import Request, urlopen

class TokenScope:
    def __init__(self, base_url="http://127.0.0.1:8000", timeout=5):
        self.url=base_url.rstrip("/")+"/api/v1/events";self.timeout=timeout

    def record(self, *, application, provider, model, input_tokens=0, output_tokens=0, **metadata):
        payload={"application":application,"provider":provider,"model":model,"input_tokens":input_tokens,"output_tokens":output_tokens,**metadata}
        request=Request(self.url,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"},method="POST")
        with urlopen(request,timeout=self.timeout) as response: return json.load(response)
