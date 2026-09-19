export const bytes=s=>new TextEncoder().encode(s).length;
export function validate(e){
 const fields=['id','kind','title','text','url','filename','collected_at'];
 if(!e||typeof e!=='object'||Object.keys(e).sort().join()!==fields.sort().join())throw Error('수집 항목 형식이 올바르지 않습니다.');
 if(typeof e.id!=='string'||!/^[0-9a-f-]{36}$/.test(e.id))throw Error('항목 ID 오류');
 for(const [k,n] of [['title',180],['text',6000],['url',1500],['filename',120],['collected_at',40]])if(typeof e[k]!=='string'||bytes(e[k])>n||e[k].includes('\0'))throw Error(`${k} 항목이 너무 길거나 올바르지 않습니다.`);
 if(!['note','link','text'].includes(e.kind)||!e.title.trim()||(!e.text.trim()&&!e.url))throw Error('제목과 내용 또는 링크를 입력하세요.');
 if(e.url){let u;try{u=new URL(e.url);}catch{throw Error('출처 URL을 확인하세요.');}if(!['http:','https:'].includes(u.protocol)||u.username||u.password)throw Error('인증 정보 없는 HTTP/HTTPS 링크만 저장할 수 있습니다.');}
 return {...e};
}
export function bundle(entries,at=new Date().toISOString()){
 if(!entries.length||entries.length>50)throw Error('한 묶음은 1~50개 항목을 선택하세요.');
 const result={schema:'cell-semi/1',exported_at:at,entries:entries.map(validate)};
 // Render this JSON using textContent; never treat it as markup.
 const json=JSON.stringify(result);if(bytes(json)>45000)throw Error('묶음이 45 KB를 넘습니다. 선택 항목을 나누어 주세요.');
 return json;
}
