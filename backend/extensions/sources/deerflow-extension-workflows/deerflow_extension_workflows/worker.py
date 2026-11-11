"""Isolated, capability-free JavaScript worker. Only bounded JSON crosses stdio."""

import json
import math
import sys

import quickjs

# One frame carries every call issued in one JS turn: 64 pending calls of
# 16,000-byte tasks must fit. Keep equal to service.FRAME.
MAX_FRAME = 2 * 1024 * 1024

BOOT = r"""
(() => {
  // Replay must not observe wall time or host randomness. These globals are
  // unavailable; callers pass timestamps and random seeds explicitly in args.
  Object.defineProperty(globalThis,'Date',{value:undefined,writable:false,configurable:false});
  Object.defineProperty(Math,'random',{value:()=>{throw new Error('Pass randomness in args');},writable:false,configurable:false});
  const encode=JSON.stringify.bind(JSON), decode=JSON.parse.bind(JSON);
  const requests=[], pending=new Map(), waiting=[]; let serial=0, final=null;
  const clone=value=>decode(encode(value));
  const freeze=value=>{if(value&&typeof value==='object'){Object.values(value).forEach(freeze);Object.freeze(value);}return value;};
  // At most 64 agent calls are outstanding at the host. Further calls wait here
  // and are issued in call order as slots free, so a wide fan-out queues
  // instead of failing; replay sees the same order.
  const issue=([payload,resolve,reject])=>{const id=++serial; requests.push({type:'agent',id,payload});pending.set(id,{resolve,reject});};
  Object.defineProperty(globalThis,'agent',{value:Object.freeze(payload=>new Promise((resolve,reject)=>{
    const call=[clone(payload),resolve,reject];
    if(pending.size<64){issue(call);return;}
    if(waiting.length>=1000){reject(new Error('More than 1,064 agent() calls are unresolved'));return;}
    waiting.push(call);
  })),writable:false,configurable:false});
  for(const name of ['pause','humanCheckpoint','captureArtifact','readArtifact']) {
    Object.defineProperty(globalThis,name,{value:Object.freeze(payload=>new Promise((resolve,reject)=>{
      if(pending.size>=64){reject(new Error('Pending call limit (64)'));return;}
      const id=++serial; requests.push({type:name,id,payload:clone(payload)});pending.set(id,{resolve,reject});
    })),writable:false,configurable:false});
  }
  Object.defineProperty(globalThis,'parallel',{value:Object.freeze(tasks=>{
    if(!Array.isArray(tasks)||tasks.length>1000) throw new Error('parallel() takes an array of at most 1,000 functions');
    return Promise.all(tasks.map(task=>task()));
  }),writable:false,configurable:false});
  // One lazy call per item with a bounded window, so a long list never holds
  // more promises than the pending-call limit; the host's slots bound real work.
  // pipeline(items, stage[, stage...][, options]): each item flows through the
  // stages in order; a later stage receives (previousResult, item, index).
  Object.defineProperty(globalThis,'pipeline',{value:Object.freeze((items,...stages)=>{
    if(!Array.isArray(items)||items.length>1000) throw new Error('pipeline() takes an array of at most 1,000 items');
    const options=stages.length&&typeof stages[stages.length-1]!=='function'?stages.pop():undefined;
    if(!stages.length||stages.some(stage=>typeof stage!=='function')) throw new Error('pipeline needs a function for each stage');
    const requested=options&&options.concurrency;
    const width=Math.max(1,Math.min(64,items.length,Number.isInteger(requested)&&requested>0?requested:16));
    const results=new Array(items.length); let next=0;
    const lane=async()=>{while(next<items.length){
      const index=next++; let value=await stages[0](items[index],index);
      for(const stage of stages.slice(1)) value=await stage(value,items[index],index);
      results[index]=value;
    }};
    return Promise.all(Array.from({length:items.length?width:0},lane)).then(()=>results);
  }),writable:false,configurable:false});
  // Progress text is cut here to just over what the host keeps (which marks the
  // cut), so a long line cannot fill the frame; never end on half a surrogate pair.
  const clip=(value,units)=>{const s=String(value).slice(0,units),last=s.charCodeAt(s.length-1);return last>=0xD800&&last<=0xDBFF?s.slice(0,-1):s;};
  const progress=message=>{
    if(requests.length>=128)throw new Error('Message limit: at most 128 log() or phase() calls without an await in between');
    requests.push(message);
  };
  Object.defineProperty(globalThis,'log',{value:Object.freeze(text=>progress({type:'log',text:clip(text,200)})),writable:false,configurable:false});
  Object.defineProperty(globalThis,'phase',{value:Object.freeze(title=>progress({type:'phase',title:clip(title,100)})),writable:false,configurable:false});
  return {
    launch:(source,args)=>{
      Object.defineProperty(globalThis,'args',{value:freeze(decode(args)),writable:false,configurable:false});
      const failed=error=>{final=encode({type:'error',message:String(error)});};
      // A script that does not parse throws here, not in the promise.
      try {
        (0,eval)('(async()=>{"use strict";\n'+source+'\n})()')
          .then(value=>{final=encode({type:'result',value:value===undefined?null:value});},failed)
          .catch(failed);  // a return value JSON cannot hold
      } catch(error) { failed(error); }
    },
    take:()=>encode(requests.splice(0)), result:()=>final,
    deliver:raw=>{const m=decode(raw),p=pending.get(m.id);if(!p)throw new Error('Unknown response');
      pending.delete(m.id);if(waiting.length&&pending.size<64)issue(waiting.shift());
      m.error?p.reject(new Error(m.error)):p.resolve(m.value);}
  };
})()
"""


def read():
    line = sys.stdin.buffer.readline(MAX_FRAME + 1)
    if not line or len(line) > MAX_FRAME or not line.endswith(b"\n"):
        raise ValueError("Invalid IPC frame")
    return json.loads(line)


def write(value):
    raw = json.dumps(value, ensure_ascii=True, allow_nan=False).encode() + b"\n"
    if len(raw) > MAX_FRAME:
        raise ValueError("IPC output limit")
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def main():
    request = read()
    # No generated Python, callbacks, imports, environment or OS bindings are exposed.
    # OS limits complement the JS engine; parent wall deadlines work on all hosts.
    try:
        import resource

        resource.setrlimit(
            resource.RLIMIT_CPU,
            (math.ceil(request["cpu_seconds"]), math.ceil(request["cpu_seconds"]) + 1),
        )
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    except ImportError:
        pass
    ctx = quickjs.Context()
    ctx.set_memory_limit(request["memory_bytes"])
    ctx.set_max_stack_size(256 * 1024)
    ctx.set_time_limit(0.05)
    ctx.eval("globalThis.__bridge = " + BOOT)
    launch = ctx.eval("__bridge.launch")
    take = ctx.eval("__bridge.take")
    result = ctx.eval("__bridge.result")
    deliver = ctx.eval("__bridge.deliver")
    ctx.eval("delete globalThis.__bridge")
    launch(request["script"], json.dumps(request["args"]))
    while True:
        # Bound each JS turn and require a parent round trip between batches.
        idle = False
        for _ in range(64):
            if not ctx.execute_pending_job():
                idle = True
                break
        messages = json.loads(take())
        outcome = result()
        # idle: the job queue drained, so only a response can make further progress.
        write({"messages": messages, "outcome": json.loads(outcome) if outcome else None, "idle": idle})
        if outcome:
            return
        response = read()
        for message in response["responses"]:
            deliver(json.dumps(message))


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        # Never return a Python traceback or worker environment to generated code.
        write(
            {
                "messages": [],
                "outcome": {
                    "type": "error",
                    "message": "Script failed or exceeded worker limits",
                },
            }
        )
        sys.exit(1)
