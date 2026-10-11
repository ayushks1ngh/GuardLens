#!/usr/bin/env python3
"""Time-bounded multi-publisher soak test using the real WebRTC source adapter.

Synthetic publishers feed distinct frames into the same frame hub used by aiortc. This
checks reconnect/isolation/latest-frame behavior without opening physical cameras.
"""
from __future__ import annotations
import argparse, threading, time, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from guardlens.capture.frame_hub import frame_hub
from guardlens.capture.worker import CaptureWorker


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--seconds",type=float,default=30); parser.add_argument("--publishers",type=int,default=3)
    args=parser.parse_args(); args.seconds=max(.5,min(args.seconds,3600)); args.publishers=max(1,min(args.publishers,32))
    stop=threading.Event(); workers=[]; threads=[]
    try:
        for index in range(args.publishers):
            stream=f"soak_{index}"; frame_hub.register(stream)
            worker=CaptureWorker(80000+index,f"webrtc:{stream}",source_type="webrtc",source_config={"mode":"publisher","stream_id":stream,"frame_timeout_ms":1000},reconnect_backoff=.1,max_backoff=.5)
            workers.append((stream,worker,index+1)); worker.start()
            def publish(s=stream,value=index+1):
                frame=np.full((120,160,3),value,dtype=np.uint8)
                while not stop.wait(1/20): frame_hub.publish(s,frame)
            thread=threading.Thread(target=publish,daemon=True);thread.start();threads.append(thread)
        deadline=time.monotonic()+args.seconds
        while time.monotonic()<deadline:
            if not all(worker.connected for _,worker,_ in workers): time.sleep(.05); continue
            for _,worker,value in workers:
                frame,_=worker.get_latest()
                if frame is None or int(frame[0,0,0])!=value: raise RuntimeError("publisher frame isolation failed")
            time.sleep(.1)
        print(f"PASS: {args.publishers} isolated publishers for {args.seconds:.1f}s")
        return 0
    finally:
        # Keep publishers alive while capture workers stop so shutdown does not
        # resemble a transport failure; then stop publisher threads and channels.
        for _,worker,_ in workers: worker.stop()
        stop.set()
        for stream,_,_ in workers: frame_hub.unregister(stream)

if __name__=="__main__": raise SystemExit(main())
