import {context,MODELS,PROFILES} from './chat-core.mjs';
const $=id=>document.getElementById(id);
let worker=null,state='checking',model=MODELS[1],history=[],output=null,timer=null,supported=false;
function status(text){$('status').textContent=text;}
function update(){
 const active=['loading','generating','clearing'].includes(state);
 $('load').disabled=!supported||active||state==='ready';$('clear').disabled=active;
 $('kill').disabled=!worker;$('send').disabled=state!=='ready';$('input').disabled=state!=='ready';$('new').disabled=active;$('new-mobile').disabled=active;
 $('progress').hidden=state!=='loading';$('profile').disabled=active||state==='ready';
 $('hint').textContent=state==='ready'?'이 기기에서 실행합니다. 오래된 문맥은 생략될 수 있습니다.':state==='generating'?'답변 생성 중 · 비상 정지로 즉시 중단할 수 있습니다.':'모델을 준비하면 대화할 수 있습니다.';
}
function stop(reason){clearTimeout(timer);worker?.terminate();worker=null;state='stopped';status(reason);update();}
function spawn(){
 worker=new Worker('./inference-worker.js',{type:'module'});
 worker.onerror=e=>stop('실행 파일을 불러오지 못했습니다. 다시 시도하거나 PC 설치 안내를 확인하세요.');
 worker.onmessage=({data})=>{
  if(data.type==='progress'){status(data.text);$('progress').value=data.progress||0;}
  if(data.type==='ready'){clearTimeout(timer);state='ready';status('준비 완료 · 모델 추론은 이 브라우저에서 실행합니다.');update();}
  if(data.type==='token'){output.textContent+=data.text;$('messages').scrollTop=$('messages').scrollHeight;}
  if(data.type==='done'){clearTimeout(timer);output.textContent=output.textContent.replace(/<think>\s*<\/think>\s*/g,'');if(output.textContent.trim())history.push({role:'assistant',content:output.textContent});state='ready';status('답변 완료 · 정확성을 확인하세요.');update();}
  if(data.type==='cleared')stop('모델 캐시를 삭제했습니다. 다른 탭에서 사용하는 캐시는 다시 생성될 수 있습니다.');
  if(data.type==='error')stop('실행 실패: '+data.text+' · GPU 메모리/네트워크를 확인한 뒤 다시 시작하세요.');
 };
}
function row(role,text){$('welcome').hidden=true;const article=document.createElement('article');article.className=role;const label=document.createElement('strong');label.textContent=role==='user'?'YOU':'CELL · LOCAL';const pre=document.createElement('pre');pre.textContent=text;article.append(label,pre);$('messages').append(article);article.scrollIntoView({block:'nearest'});return pre;}
$('load').onclick=()=>{stop('모델을 준비합니다…');state='loading';$('progress').value=0;spawn();worker.postMessage({type:'load',model,profile:$('profile').value});timer=setTimeout(()=>stop('모델 준비 시간이 15분을 넘었습니다. 연결을 확인하고 다시 시작하세요.'),900000);update();};
$('kill').onclick=()=>stop('중지됨 · 추론 작업자를 종료했습니다. 다시 시작하면 캐시를 사용해 모델을 불러옵니다.');
$('clear').onclick=()=>{stop('캐시 삭제 중…');state='clearing';spawn();worker.postMessage({type:'clear',models:MODELS});timer=setTimeout(()=>stop('캐시 삭제를 완료하지 못했습니다. 브라우저의 사이트 데이터 설정에서도 지울 수 있습니다.'),30000);update();};
$('new').onclick=()=>{history=[];for(const a of $('messages').querySelectorAll('article'))a.remove();$('welcome').hidden=false;$('input').value='';};
$('new-mobile').onclick=$('new').onclick;
$('composer').onsubmit=e=>{e.preventDefault();if(state!=='ready')return;const text=$('input').value.trim();let messages;try{messages=context(history,text,$("profile").value);}catch(e){status(e.message);return;}history.push({role:'user',content:text});history=history.slice(-24);row('user',text);output=row('assistant','');$('input').value='';state='generating';status('이 기기에서 답변 생성 중…');worker.postMessage({type:'chat',messages});timer=setTimeout(()=>stop('생성 시간이 2분을 넘어서 중지했습니다. 더 짧은 질문으로 다시 시도하세요.'),120000);update();};
$('input').onkeydown=e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();$('composer').requestSubmit();}};
for(const button of document.querySelectorAll('[data-prompt]'))button.onclick=()=>{$('input').value=button.dataset.prompt;if(state==='ready')$('input').focus();};
window.addEventListener('pagehide',()=>stop('탭을 떠나 추론 작업자를 종료했습니다.'));
async function check(){try{
 if(!isSecureContext)throw Error('HTTPS 또는 localhost에서 열어 주세요.');
 if(!navigator.gpu)throw Error('이 브라우저는 WebGPU를 제공하지 않습니다. 지원 브라우저 또는 PC 실행을 사용하세요.');
 const adapter=await navigator.gpu.requestAdapter();if(!adapter)throw Error('사용 가능한 WebGPU 장치를 찾지 못했습니다. 브라우저 하드웨어 가속과 GPU 지원을 확인하세요.');
 model=adapter.features.has('shader-f16')?MODELS[0]:MODELS[1];supported=true;state='idle';$('support').textContent='WebGPU 감지됨 · '+(model===MODELS[0]?'GPU 메모리 약 1.4 GB':'GPU 메모리 약 1.9 GB')+' 필요 추정. 실제 로딩 성공은 별도 확인이 필요합니다.';
}catch(e){state='unsupported';$('support').textContent=e.message;status('이 환경에서는 브라우저 추론을 시작할 수 없습니다. PC 설치 안내를 확인하세요.');}update();}
check();

// Hidden mobile pages may be frozen or evicted. Stop rather than leaving an ambiguous task.
document.addEventListener('visibilitychange',()=>{if(document.hidden&&worker)stop('앱이 배경으로 이동해 모델 실행을 중지했습니다. 돌아와서 모델을 다시 시작하세요.');});
$('profile').onchange=()=>{const p=PROFILES[$('profile').value];$('input').maxLength=p.input;status(`설정 변경: 질문 ${p.input}바이트, 답변 ${p.output}토큰까지. 모델을 시작하세요.`);};
$('input').maxLength=PROFILES[$('profile').value].input;
if(navigator.storage?.estimate)navigator.storage.estimate().then(({quota,usage})=>{if(Number.isFinite(quota)&&Number.isFinite(usage))$('storage').textContent=`브라우저 저장 공간 여유 추정: ${((quota-usage)/1024**3).toFixed(1)} GB · 실제 메모리 여유와는 다릅니다.`;}).catch(()=>{});
let installPrompt;
window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();installPrompt=e;$('install').hidden=false;});
$('install').onclick=async()=>{if(!installPrompt)return;await installPrompt.prompt();await installPrompt.userChoice;installPrompt=null;$('install').hidden=true;};
window.addEventListener('appinstalled',()=>{$('install').hidden=true;$('install-note').textContent='홈 화면 설치 완료 · 추론은 앱을 열어 둔 동안 실행합니다.';});
if('serviceWorker' in navigator&&isSecureContext)navigator.serviceWorker.register('./cell-sw.js').catch(()=>{$('install-note').textContent+=' 화면 오프라인 캐시 등록 실패. 온라인에서 사용하세요.';});
