"""Bounded Windows CPU LoRA experiment. Candidate only; never replaces serving weights."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

MODEL='Qwen/Qwen3-0.6B'
REVISION='c1899de289a04d12100db370d81485cdf75e47ca'

def dataset(path):
    rows=[json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
    if not 8<=len(rows)<=500:raise ValueError('8–500 authored examples required')
    seen=set()
    for row in rows:
        if set(row)!={'split','prompt','answer'} or row['split'] not in {'train','eval'}:raise ValueError('Invalid dataset schema')
        if not all(isinstance(row[k],str) and 1<=len(row[k])<=800 for k in ('prompt','answer')):raise ValueError('Invalid text')
        key=row['prompt'].strip().lower()
        if key in seen:raise ValueError('Duplicate or train/eval leakage')
        seen.add(key)
    if sum(r['split']=='eval' for r in rows)<4:raise ValueError('At least four held-out examples required')
    return rows

def worker(args):
    if sys.stdin.readline().strip()!='START':raise RuntimeError('Supervisor gate missing')
    os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
    os.environ['HF_HUB_DISABLE_XET']='1'
    os.environ['TOKENIZERS_PARALLELISM']='false'
    os.environ['HF_HOME']=str(Path(args.cache).resolve())
    import random
    import torch
    from transformers import AutoModelForCausalLM,AutoTokenizer
    from peft import LoraConfig,get_peft_model
    torch.set_num_threads(2);torch.manual_seed(42);random.seed(42)
    rows=dataset(args.data)
    print('Loading pinned public base model; paid inference is not used.',flush=True)
    tokenizer=AutoTokenizer.from_pretrained(MODEL,revision=REVISION,trust_remote_code=False)
    base=AutoModelForCausalLM.from_pretrained(MODEL,revision=REVISION,trust_remote_code=False,use_safetensors=True,torch_dtype=torch.float32,attn_implementation='eager')
    model=get_peft_model(base,LoraConfig(r=4,lora_alpha=8,lora_dropout=0.05,target_modules=['q_proj','v_proj'],task_type='CAUSAL_LM'))
    model.config.use_cache=False
    model.gradient_checkpointing_enable();model.enable_input_require_grads()
    def encoded(row):
        prefix=tokenizer.apply_chat_template([{'role':'user','content':row['prompt']}],tokenize=True,add_generation_prompt=True,enable_thinking=False)
        target=tokenizer.encode(row['answer']+'<|im_end|>',add_special_tokens=False)
        if len(prefix)+len(target)>256:raise ValueError('Example exceeds 256 tokens; shorten it rather than silently truncating the answer')
        ids=torch.tensor([prefix+target]);labels=torch.tensor([[-100]*len(prefix)+target])
        return dict(input_ids=ids,attention_mask=torch.ones_like(ids),labels=labels)
    train=[encoded(r) for r in rows if r['split']=='train'];tests=[encoded(r) for r in rows if r['split']=='eval']
    def measure():
        model.eval()
        with torch.no_grad():return [float(model(**example).loss) for example in tests]
    def samples():
        model.eval();items=[]
        with torch.no_grad():
            for row in [r for r in rows if r['split']=='eval'][:2]:
                ids=tokenizer.apply_chat_template([{'role':'user','content':row['prompt']}],tokenize=True,add_generation_prompt=True,enable_thinking=False,return_tensors='pt')
                out=model.generate(input_ids=ids,attention_mask=torch.ones_like(ids),max_new_tokens=80,do_sample=False,pad_token_id=tokenizer.eos_token_id,use_cache=True)
                items.append(dict(prompt=row['prompt'],answer=tokenizer.decode(out[0,ids.shape[1]:],skip_special_tokens=True)))
        return items
    before=measure();before_samples=samples();print('Baseline evaluated.',flush=True)
    opt=torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],lr=5e-5)
    losses=[]
    for step in range(args.steps):
        if (Path(args.output).parent/'STOP').exists():raise RuntimeError('Training STOP requested')
        model.train();opt.zero_grad(set_to_none=True)
        loss=model(**train[step%len(train)]).loss
        if not torch.isfinite(loss):raise ValueError('Non-finite loss')
        loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1.0);opt.step()
        losses.append(float(loss.detach()));print(f'Step {step+1}/{args.steps}, loss={losses[-1]:.4f}',flush=True)
    after=measure();after_samples=samples()
    output=Path(args.output);output.mkdir(parents=True,exist_ok=False)
    model.save_pretrained(output/'adapter',safe_serialization=True)
    avg=lambda x:sum(x)/len(x)
    report=dict(schema='cell-language-experiment/1',model=MODEL,revision=REVISION,seed=42,steps=args.steps,
        dataset_sha256=hashlib.sha256(Path(args.data).read_bytes()).hexdigest(),train_examples=len(train),held_out_examples=len(tests),
        train_loss=losses,held_out_before=before,held_out_after=after,mean_before=avg(before),mean_after=avg(after),
        before_samples=before_samples,after_samples=after_samples,parameters_trainable=sum(p.numel() for p in model.parameters() if p.requires_grad),
        held_out_proxy_improved=avg(after)<avg(before)*.97 and max(a-b for a,b in zip(after,before))<.3,
        status='candidate_not_deployed',human_language_quality='not_evaluated',warning='Tiny synthetic evaluation is not proof of general intelligence or conversational improvement.')
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('status','mean_before','mean_after','held_out_proxy_improved')},ensure_ascii=False),flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--data',default=str(Path(__file__).with_name('language-curriculum.jsonl')))
    p.add_argument('--output',required=True);p.add_argument('--cache',required=True);p.add_argument('--steps',type=int,default=16)
    p.add_argument('--minutes',type=int,default=20);p.add_argument('--worker',action='store_true')
    a=p.parse_args()
    if not 1<=a.steps<=64 or not 1<=a.minutes<=30:raise ValueError('Budget: 1–64 steps and 1–30 minutes')
    dataset(a.data)
    if a.worker:return worker(a)
    root=Path(a.output).resolve().parent;root.mkdir(parents=True,exist_ok=True)
    if (root/'STOP').exists():raise RuntimeError('Remove the experiment STOP file explicitly to resume')
    if Path(a.output).exists():raise ValueError('Use a new experiment directory; earlier results are preserved')
    from process_guard import ProcessGuard
    guard=ProcessGuard(memory_mb=12288,cpu_percent=25)
    lock=root/'training.lock'
    try:lockfd=os.open(str(lock),os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        guard.close();raise RuntimeError('Training lock exists; inspect the running experiment before removing a stale lock')
    os.write(lockfd,str(os.getpid()).encode());os.close(lockfd)
    proc=None
    try:
        proc=subprocess.Popen([sys.executable,'-X','utf8',__file__,*sys.argv[1:],'--worker'],stdin=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        guard.attach(proc);proc.stdin.write(b'START\n');proc.stdin.close();deadline=time.monotonic()+a.minutes*60
        while proc.poll() is None:
            if (root/'STOP').exists() or time.monotonic()>deadline:
                guard.kill();raise RuntimeError('Training stopped by STOP file or time budget; serving model remains unchanged')
            time.sleep(.5)
        if proc.returncode:raise RuntimeError(f'Experiment worker failed ({proc.returncode}); inspect log')
        print('Peak supervised RAM bytes:',guard.peak_bytes(),flush=True)
    finally:
        if proc is not None and proc.poll() is None:proc.kill()
        guard.close();lock.unlink(missing_ok=True)

if __name__=='__main__':main()
