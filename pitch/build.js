const pptxgen = require('pptxgenjs');
const path = process.argv[2];
const pres = new pptxgen();
pres.layout = 'LAYOUT_WIDE';
pres.title = 'Anarcha AI: how it works';
const S = [
 ['WITH ANARCHA AI','Same patient. Same GP.',"Let's go back to the woman from the video. Same symptoms: she's tired, breathless, her ankles are swollen and her jaw aches."],
 ['WITH ANARCHA AI','This time, the GP asks Anarcha',"Same GP. But this time he types her symptoms into Anarcha and attaches her ECG. So what happens behind that screen?"],
 ['STEP 1 · THE DATA','Studies in which only women took part',"Step one is the data. We collect medical studies from Europe PMC and keep only those in which only women took part. A program checks every study and saves the sentence that proves it. That leaves 50,748 studies."],
 ['STEP 1 · THE DATA',"A map of women's health research","A computer places similar studies close together. This is the map of women's health research. It also shows where research on women is missing."],
 ['STEP 2 · SYMPTOM FILTER','Her words find the studies',"Step two uses her own words. We zoom in on about 5,500 heart studies. 855 of them describe the symptoms the women in the study actually had."],
 ['STEP 2 · SYMPTOM FILTER','280 studies match her symptoms',"Her four symptoms light up 280 studies: research on women with her complaints. And 'no chest pain' does not count as chest pain."],
 ['STEP 3 · ECG AI','A second AI reads her heart signal',"Step three: a second AI reads her ECG. We trained it ourselves on 80,000 ECGs, and it tells a female from a male heart signal with 93% accuracy."],
 ['STEP 3 · ECG AI','Her ECG looks more male than most',"Her ECG looks more male than most women's. In our data, the women with the most male-looking ECGs died more than twice as often within four years. That is a group risk, not her diagnosis."],
 ['STEP 4 · DECISION TREE','Yes or no, step by step',"Step four is a decision tree, learned from 855 studies. Simple yes-or-no questions: not pregnant, no chest pain, but short of breath. That points to research on heart failure, and the GP can see exactly why."],
 ['STEP 5 · REASONING AGENT','Everything comes together, with sources',"Step five: the reasoning agent brings the studies, the ECG and the tree together. It answers with sources and never diagnoses. The doctor decides."],
 ['WITH ANARCHA AI','Referred straight away, not sent home',"And this time she is not sent home. She is referred to a cardiologist straight away."],
];
S.forEach(([tag, title, note], i) => {
  const s = pres.addSlide();
  s.background = { path: `${path}/s${i+1}.png` };
  const tw = 0.13 * tag.length + 0.5;
  s.addText(tag, { shape: pres.shapes.ROUNDED_RECTANGLE, rectRadius: 0.5, x: (13.333 - tw)/2, y: 0.28, w: tw, h: 0.32,
    fill: { color: 'F27383' }, color: 'FFFFFF', fontFace: 'Poppins', fontSize: 11, bold: true, align: 'center', valign: 'middle', margin: 0, objectName: 'Tag' });
  s.addText(title, { x: 0.8, y: 0.62, w: 11.733, h: 0.75, fontFace: 'Poppins', fontSize: 32, bold: true, color: '5C2234',
    align: 'center', valign: 'middle', margin: 0, isTextBox: true, objectName: 'Title' });
  s.addNotes(note);
});
pres.writeFile({ fileName: `${path}/../deck/Anarcha_AI_methods.pptx` }).then(f => console.log('wrote', f));
