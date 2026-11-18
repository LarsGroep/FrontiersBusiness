const pptxgen = require('pptxgenjs');
const path = process.argv[2];
const ACC = process.argv[3] || '–';
const pres = new pptxgen();
pres.layout = 'LAYOUT_WIDE';
pres.title = 'Anarcha AI: how it works';
const S = [
 ['WITH ANARCHA AI','Same patient. Same GP.',"Let's go back to the woman from the video. Same symptoms: she's tired, breathless, her ankles are swollen and her jaw aches."],
 ['WITH ANARCHA AI','This time, the GP asks Anarcha',"Same GP. But this time he types her symptoms into Anarcha and attaches her ECG. So what happens behind that screen?"],
 ['STEP 1 · THE DATA','Studies in which only women took part',"Step one is the data. We collect medical studies from Europe PMC and keep only those in which only women took part. A program checks every study and saves the sentence that proves it. That leaves 50,748 studies."],
 ['STEP 1 · THE DATA','Similar studies group into themes',"A computer reads every study and places similar ones close together. Each dot is one study. The computer found 30 research themes on its own; here they are coloured in 9 groups, from cancer to pregnancy."],
 ['STEP 1 · THE DATA','Two themes are about the heart',"Two of those themes are about the heart: the heart in general, and high blood pressure in pregnancy. That is where we zoom in."],
 ['STEP 2 · SYMPTOM FILTER','Her words find the studies',`Step two uses her own words. We zoom in on about 5,500 heart studies; 855 of them describe the symptoms the women actually had. Her ECG goes in too: our ECG AI, trained only on women, recognises heart problems with ${ACC}% accuracy.`],
 ['STEP 2 · SYMPTOM FILTER','280 studies match her symptoms',"Her four symptoms light up 280 studies: research on women with her complaints. Then a small decision tree, learned from 855 studies, asks yes or no: not pregnant, no chest pain, but short of breath. That points to research on heart failure, and the GP can see exactly why."],
 ['STEP 3 · REASONING AGENT','Everything comes together, with sources',"Step three: the reasoning agent brings the studies, the ECG and the tree together. It answers with sources and never diagnoses. The doctor decides."],
 ['WITH ANARCHA AI','Referred straight away, not sent home',"And this time she is not sent home. She is referred to a cardiologist straight away. This may sound too good to be true, but it can happen now: this is our working prototype."],
];
S.forEach(([tag, title, note], i) => {
  const s = pres.addSlide();
  s.background = { path: `${path}/m${i+1}.png` };
  const tw = 0.13 * tag.length + 0.5;
  s.addText(tag, { shape: pres.shapes.ROUNDED_RECTANGLE, rectRadius: 0.5, x: (13.333 - tw)/2, y: 0.28, w: tw, h: 0.32,
    fill: { color: 'F27383' }, color: 'FFFFFF', fontFace: 'Poppins', fontSize: 11, bold: true, align: 'center', valign: 'middle', margin: 0, objectName: 'Tag' });
  s.addText(title, { x: 0.8, y: 0.62, w: 11.733, h: 0.75, fontFace: 'Poppins', fontSize: 32, bold: true, color: '5C2234',
    align: 'center', valign: 'middle', margin: 0, isTextBox: true, objectName: 'Title' });
  if (i === 5 || i === 6) {
    s.addText(`${ACC}% accuracy`, { x: 2.68, y: 3.12, w: 2.0, h: 0.32, fontFace: 'Poppins', fontSize: 13, bold: true, color: 'E65C6E',
      align: 'center', valign: 'middle', margin: 0, isTextBox: true, objectName: 'ECG accuracy' });
  }
  s.addNotes(note);
});
pres.writeFile({ fileName: `${path}/../deck/Anarcha_AI_methods.pptx` }).then(f => console.log('wrote', f));
