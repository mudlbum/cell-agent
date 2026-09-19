export const MODELS=['Qwen3-0.6B-q4f16_1-MLC','Qwen3-0.6B-q4f32_1-MLC'];
const bytes=s=>new TextEncoder().encode(s).length;
export const PROFILES=Object.freeze({compact:{window:2048,output:256,input:900,budget:1100},balanced:{window:4096,output:512,input:1800,budget:2200}});
export function context(history,input,profile="balanced"){
 const limits=PROFILES[profile];if(!limits)throw Error("지원하지 않는 실행 설정입니다.");
 if(!input.trim())throw Error('메시지를 입력하세요.');
 if(bytes(input)>limits.input)throw Error(`이 설정의 질문 한도는 UTF-8 ${limits.input}바이트입니다. 나누어 보내 주세요.`);
 let left=limits.budget-bytes(input),recent=[];
 for(const m of history.slice(-12).reverse()){
  if(!['user','assistant'].includes(m.role)||typeof m.content!=='string')continue;
  if(bytes(m.content)>left)break;
  recent.push({role:m.role,content:m.content});left-=bytes(m.content);
 }
 return [{role:'system',content:'You are Cell. Reply in the user language. Be concise and honest. You can only answer as text; you cannot browse, execute code or access files. /no_think'},...recent.reverse(),{role:'user',content:input}];
}
