import fs from 'node:fs/promises';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
const p=await PresentationFile.importPptx(await FileBlob.load('C:/Users/T460S/Downloads/Pittsburgh_IQ_Pitch.pptx'));
await fs.mkdir('.presentation-build/reference',{recursive:true});
for(let i=0;i<p.slides.items.length;i++){const b=await p.export({slide:p.slides.items[i],format:'png',scale:1});await fs.writeFile(`.presentation-build/reference/${i+1}.png`,new Uint8Array(await b.arrayBuffer()));}
