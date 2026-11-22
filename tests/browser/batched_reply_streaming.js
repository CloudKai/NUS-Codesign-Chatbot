/** Verify distinct paints when an entire real mock NDJSON response arrives in one burst. */
async page => {
  const assert=(value,message)=>{if(!value)throw Error(message)};
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const composer=page.getByRole('textbox',{name:'Your project contribution',exact:true});
  await composer.waitFor();
  await page.bringToFront();
  await page.evaluate(()=>Object.defineProperty(document,'hidden',{configurable:true,value:false}));
  let bursts=0;
  await page.route('**/stream',async route=>{
    const response=await route.fetch();
    const body=await response.text();
    assert(body.includes('"event": "reply_delta"'),'Fixture must provide actual fragments');
    bursts++;
    await route.fulfill({response,body});
  });
  async function observe(action){
    await page.evaluate(()=>{
      const sizes=[];
      const observer=new MutationObserver(()=>{
        const size=document.querySelector('.message.preview .message-content')?.textContent?.length||0;
        if(size && size!==sizes.at(-1))sizes.push(size);
      });
      window.__replyObserver?.disconnect();
      window.__replyObserver=observer;
      observer.observe(document.body,{subtree:true,childList:true,characterData:true});
      window.__replySizes=sizes;
    });
    await action.click();
    try { await page.waitForFunction(()=>window.__replySizes.length>=3,null,{timeout:4000}); }
    catch { throw Error(JSON.stringify({bursts,sizes:await page.evaluate(()=>window.__replySizes),errors})); }
    await page.getByRole('button',{name:'Stop generating',exact:true}).waitFor({state:'hidden'});
    const sizes=await page.evaluate(()=>{window.__replyObserver.disconnect(); return window.__replySizes;});
    assert(sizes.at(-1)>sizes[0],'Preview must grow across separate paints');
    return sizes;
  }
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.setViewportSize({width:390,height:880});
  await composer.fill('Older residents need safer crossing times near the market.');
  const send=await observe(page.getByRole('button',{name:'Send message',exact:true}));
  await page.locator('.message.student').last().getByRole('button',{name:'Edit message',exact:true}).click();
  await page.getByRole('textbox',{name:'Revise your message',exact:true}).fill('Older residents need longer crossing times near this market.');
  const edit=await observe(page.getByRole('button',{name:'Confirm edit & ask again',exact:true}));
  assert(bursts===2 && !errors.length,JSON.stringify({bursts,errors}));
  await page.setViewportSize({width:1440,height:900});
  await page.getByRole('button',{name:'Settings',exact:true}).click();
  await page.getByText('Appearance',{exact:true}).waitFor();
  assert(await page.getByText('Reduce motion',{exact:true}).count()===0,'Remove app setting');
  return {send,edit,bursts,errors};
}
