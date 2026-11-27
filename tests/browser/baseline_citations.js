/** Verify local upload, citation and saved-turn receipt through the disposable 8093 browser/API seam. */
async page => {
  await page.goto('http://127.0.0.1:8093/');
  const nav=page.getByRole('complementary',{name:'Your notebooks'}); await nav.waitFor();
  const fixture=await page.evaluate(async()=>{
    const req=async(path,body)=>{const r=await fetch('/api/v1/reader'+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{}); if(!r.ok)throw Error(path+': '+r.status);return r;};
    const {notebook}=await(await req('/threads',{kind:'chat'})).json(); const path='/threads/'+notebook.id;
    await req(path+'/settings',{name:'Ticket 01 cited evidence'});
    const form=new FormData(); form.append('files',new Blob(['Analogy supports design ideation using familiar comparisons.'],{type:'text/plain'}),'baseline.txt');
    const upload=await fetch('/api/v1/reader'+path+'/uploads',{method:'POST',body:form}); if(upload.status!==202)throw Error('Upload failed');
    for(let i=0;i<100;i++){const jobs=await(await req(path+'/uploads')).json(); if(jobs.jobs[0]?.state==='saved')break;await new Promise(r=>setTimeout(r,50));}
    const source=(await(await req(path+'/sources')).json()).sources[0]; if(!source)throw Error('No saved source');
    const key=notebook.id+'-citation'; const stream=await(await req(path+'/lecture/stream',{student_message:'Explain analogy in design',idempotency_key:key})).text();
    const events=stream.trim().split('\n').map(JSON.parse);const done=events.find(e=>e.event==='done');if(!done?.turn.assessment.citations.length)throw Error('Missing grounded done citation');
    const recovered=await(await req(path+'/coach-turn?idempotency_key='+key)).json();if(JSON.stringify(recovered)!==JSON.stringify(done.turn))throw Error('Exact-key recovery mismatch');
    const messages=(await(await req(path+'/messages/page')).json()).messages;if(messages.length!==2)throw Error('Duplicate turn'); const msg=messages.at(-1);
    const original=await req(path+'/messages/'+msg.id+'/citations/'+source.id+'/content');if(await original.text()!=='Analogy supports design ideation using familiar comparisons.')throw Error('Original differs');
    window.__ticket01Citation={path,key,turn:done.turn};return {id:notebook.id,citations:msg.citations,events:events.map(e=>e.event)};
  });
  await page.reload();await nav.getByRole('button',{name:'Ticket 01 cited evidence',exact:true}).click();
  const evidence=page.getByRole('button').filter({hasText:'baseline.txt'}); await evidence.first().click();
  await page.getByRole('complementary',{name:'Cited evidence'}).getByText('Analogy supports design ideation using familiar comparisons.',{exact:true}).waitFor();
  await page.screenshot({path:'output/playwright/summary-30/ticket01-citation.png'});
  return {result:'PASS: real upload, local retrieval, saved citation, exact original, exact-key recovery, two rows and visible excerpt',...fixture};
}
