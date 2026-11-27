/** Verify a pending recommendation stays put until the student confirms through the disposable 8093 UI. */
async page=>{
 const nav=page.getByRole('complementary',{name:'Your notebooks'});
 const fixture=await page.evaluate(async()=>{
 const req=async(path,body)=>{const r=await fetch('/api/v1/reader'+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});if(!r.ok)throw Error(path+': '+r.status);return r;};
 const {notebook}=await(await req('/threads',{kind:'chat'})).json();const path='/threads/'+notebook.id;
 await req(path+'/settings',{name:'Ticket 01 confirmation',response_detail:'short'});
 for(let i=0;i<2;i++){const text=await(await req(path+'/project/stream',{student_message:'Older residents need to cross safely to reach the shops.',idempotency_key:notebook.id+'-'+i})).text();if(!text.includes('"event": "done"'))throw Error('Missing done');}
 const project=await(await req(path+'/project')).json();if(project.current_stage!=='problem_identification'||!project.pending)throw Error('Advanced before confirmation');return {path};});
 await page.reload();await nav.getByRole('button',{name:'Ticket 01 confirmation',exact:true}).click();
 await page.getByRole('radio',{name:'Design coaching',exact:true}).check();
 await page.getByRole('button',{name:'Move to Concept generation',exact:true}).click();
 await page.waitForFunction(async path=>(await(await fetch('/api/v1/reader'+path+'/project')).json()).current_stage==='concept_generation',fixture.path);
 await page.reload();await page.getByRole('textbox',{name:'Your project contribution',exact:true}).waitFor();
 const view=await page.evaluate(async path=>(await(await fetch('/api/v1/reader'+path+'/project')).json()),fixture.path);
 if(view.current_stage!=='concept_generation'||view.pending!==null)throw Error('Confirmation not saved');
 return 'PASS: proposal stayed in Problem identification until visible Move action, then saved Concept generation survives reload';
}
