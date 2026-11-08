// Capability questions are answered by the phone, independently of the chat model.
export async function describeChatCapabilities({input,previousInput='',origin,shelf,web}){
 if(origin!=='user')return null;
 const clean=value=>value.trim().replace(/\s+/g,'').replace(/[？?。！!]+$/,'');
 let question=clean(input);
 if(/^(?:现在呢|现在可以了吗|现在能了吗)$/.test(question))question=clean(previousInput);
 // A narrow speech-recognition homophone in a combined capability question.
 question=question.replace(/(看见|看到)暑假((?:或者|还是|和|与)(?:联网|上网)(?:吗|么)?$)/,'$1书架$2');
 const book='(?:手机)?(?:书架(?:目录)?|分类资料(?:目录)?|阅读目录)';
 const net='(?:联网|上网)';
 const connector='(?:或者|还是|和|与|及|、|，|,)';
 const target='(?:'+book+'|'+net+')';
 const both=new RegExp('^(?:你)?(?:能不能|能否|能|可以)?(?:看到|看见|读取|读到|看|读)?'+target+connector+'(?:能不能|能否|能|可以)?(?:看到|读取|看|读)?'+target+'(?:吗|么)?$');
 const askBook=new RegExp('^(?:你)?(?:现在)?(?:能不能|能否|能|可以)(?:看到|看见|读取|读到|看|读)'+book+'(?:吗|么)?$');
 const askNet=new RegExp('^(?:你)?(?:现在)?(?:能不能|能否|能|可以)'+net+'(?:吗|么)?$');
 const mixed=both.test(question);
 const [bookState,netState]=await Promise.all([
  askBook.test(question)||(mixed&&new RegExp(book).test(question))?shelf?.describe():null,
  askNet.test(question)||(mixed&&new RegExp(net).test(question))?web?.describe():null
 ]);
 return [bookState&&'书架：'+bookState,netState&&'联网：'+netState].filter(Boolean).join('\n\n')||null;
}
