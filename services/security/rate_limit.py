from collections import defaultdict, deque
from threading import Lock
from time import monotonic

class SlidingWindowLimiter:
    def __init__(self,limit=600,window=60): self.limit=limit;self.window=window;self.events=defaultdict(deque);self.lock=Lock()
    def allow(self,key):
        now=monotonic()
        with self.lock:
            bucket=self.events[key]
            while bucket and bucket[0]<=now-self.window: bucket.popleft()
            if len(bucket)>=self.limit: return False
            bucket.append(now);return True
