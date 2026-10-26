"""Chinese communication reports using the existing report font and render pool."""
import io
import json
import math
from html import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,Flowable
from src import pdf_report,communications as c
from src.communication_studio import validate_document
from src.workbench import VERSION
from src.communication_report_materials import prepare, MaterialFigure

def printable(value):
    text=str(value).translate(str.maketrans('₀₁₂₃₄₅₆₇₈₉','0123456789'))
    return ''.join(ch for ch in text if ord(ch)<=0xffff and not 0x2600<=ord(ch)<=0x27bf and ch not in '\ufe0f\u200d')


def facts(raw):
    doc=validate_document(raw);built=c.build(doc['program']);result=doc.get('result')
    if result:
        frame=result.get('experience',{}).get('frame',0)
        if not isinstance(frame,int) or not 0<=frame<c.CONFIG['max_continuous_frames']: raise ValueError('结果帧序号无效。')
        expected=(doc['program']['seed']+frame)%4294967295
        if result.get('seed')!=expected: raise ValueError('结果与当前随机种子不一致，请重新运行。')
        candidate={**doc['program'],'seed':expected}
        if c.build(candidate)['token']!=result.get('token'): raise ValueError('结果与当前链路不一致，请重新运行后生成报告。')
    curves=doc.get('sweeps',[])
    if not isinstance(curves,list) or len(curves)>6: raise ValueError('报告最多包含 6 条性能曲线。')
    summary=[]
    if result:
        m=result['metrics']
        if m.get('ber') is not None: summary.append(f"接收 {m['bit_count']} 位，错误 {m['bit_errors']} 位，BER={m['ber']:.5g}。")
        elif m.get('received_bits') is not None: summary.append(f"录波接收 {m['received_bits']} 位，接收功率 {m['rx_power']:.5g}。")
        if m.get('net_bit_rate') is not None: summary.append(f"净信息速率 {m['net_bit_rate']:.5g} bit/s；频谱效率 {m['spectral_efficiency']:.5g} bit/s/Hz（99% 占用带宽）；PAPR {m['papr_db']:.5g} dB。")
        if m.get('rmse') is not None: summary.append(f"信宿 RMSE={m['rmse']:.5g}。")
    for curve in curves:
        if not isinstance(curve,dict) or not isinstance(curve.get('points'),list) or len(curve['points'])>21: raise ValueError('扫描曲线格式无效。')
        if curve['points']:
            first,last=curve['points'][0],curve['points'][-1]
            metric='ber' if any(p.get('bit_count') for p in curve['points']) else 'rmse'
            summary.append(f"{str(curve.get('name','性能扫描'))[:80]}：参数 {first['db']:g} → {last['db']:g}，观测 {metric.upper()} {first[metric]:.5g} → {last[metric]:.5g}，累计 {sum(p['frames'] for p in curve['points'])} 帧。")
    available,selected,conclusion=prepare(doc)
    return {'document':doc,'build':built,'summary':summary or ['工程已构建，尚未保存运行结果。'],'app_version':VERSION,
            'sections':['实验链路与参数','接收结果','性能曲线与统计',*[v['title'] for v in selected],'结论与复现'],
            'materials':available,'selected_materials':selected,'conclusion':conclusion}


class Diagram(Flowable):
    def __init__(self,labels):
        super().__init__();self.labels=labels;self.width=490;self.height=math.ceil(len(labels)/4)*48+8
    def draw(self):
        canvas=self.canv;canvas.setFont(pdf_report.FONT,8)
        for i,label in enumerate(self.labels):
            col=i%4;row=i//4;x=col*122;y=self.height-42-row*48
            canvas.setFillColor(colors.HexColor('#e6f1fb'));canvas.setStrokeColor(colors.HexColor('#7489b9'));canvas.roundRect(x,y,110,32,6,fill=1)
            canvas.setFillColor(colors.HexColor('#263858'))
            for j,part in enumerate([label[:11],label[11:22]]): canvas.drawCentredString(x+55,y+19-j*11,part)
            if col<3 and i<len(self.labels)-1: canvas.line(x+111,y+16,x+121,y+16)


class Curve(Flowable):
    def __init__(self,curves): super().__init__();self.curves=curves;self.width=490;self.height=220
    def draw(self):
        cv=self.canv;left,bottom,w,h=43,28,427,170;points=[p for s in self.curves for p in s['points']]
        if not points:return
        low=min(p['db'] for p in points);high=max(p['db'] for p in points)
        metric='ber' if any(p.get('bit_count') for p in points) else 'rmse';top=max(1e-8,max(p.get('rmse',0) for p in points))*1.1
        px=lambda v:left+(v-low)/max(high-low,1)*w
        py=lambda v:bottom+((max(-6,min(0,math.log10(max(v,1e-6))))+6)/6 if metric=='ber' else v/top)*h
        cv.setFont(pdf_report.FONT,8);cv.setStrokeColor(colors.HexColor('#d4deed'))
        for exp in range(-6,1):
            y=bottom+(exp+6)/6*h;cv.line(left,y,left+w,y);cv.setFillColor(colors.HexColor('#526b8e'));cv.drawRightString(left-5,y-3,f'10^{exp}' if metric=='ber' else f'{(exp+6)/6*top:.3g}')
        for i in range(5):
            value=low+(high-low)*i/4;x=px(value);cv.line(x,bottom,x,bottom+h);cv.drawCentredString(x,bottom-13,f'{value:g}')
        palette=['#5365cf','#238879','#af5390','#bd7a21','#3797b5','#8059a6']
        for i,s in enumerate(self.curves):
            cv.setStrokeColor(colors.HexColor(palette[i]));cv.setFillColor(colors.HexColor(palette[i]));last=None
            for p in s['points']:
                value=p[metric];ci=p.get(metric+'_interval',[value,value]);x,y=px(p['db']),py(value or ci[1])
                if last:cv.line(*last,x,y)
                cv.line(x,py(ci[0]),x,py(ci[1]));cv.circle(x,y,2,fill=int(value>0));last=x,y
            cv.drawString(left+6,bottom+h-12-i*11,str(s.get('name','曲线'))[:30])
        cv.setFillColor(colors.HexColor('#526b8e'));cv.drawString(left,self.height-8,'BER / 95% Wilson 区间' if metric=='ber' else 'RMSE');cv.drawRightString(left+w,3,printable(self.curves[0].get('axis','参数')))


def render(raw):
    f=facts(raw)
    if not pdf_report.RENDER_LIMIT.acquire(blocking=False):
        from src.tasks import TaskBusy
        raise TaskBusy('报告生成繁忙，请稍后重试。')
    try:
        pdf_report._font();font=pdf_report.FONT;output=io.BytesIO();styles={}
        for name,size,color in [('title',23,'#344a83'),('heading',13,'#5967b9'),('body',9,'#263858')]:
            styles[name]=ParagraphStyle(name,fontName=font,fontSize=size,leading=size*1.6,textColor=colors.HexColor(color),wordWrap='CJK',spaceAfter=10)
        styles['heading'].keepWithNext=True
        paragraph=lambda text,style='body':Paragraph(escape(printable(text)),styles[style])
        doc=f['document'];story=[paragraph(doc['name'],'title'),paragraph(f"通信原理实验报告 · v{VERSION}"),paragraph('实验链路与参数','heading')]
        blocks=doc['program']['blocks'];story.append(Diagram([printable(c.BLOCKS[b['kind']]['label']).strip() for b in blocks]))
        rows=[[paragraph('模块'),paragraph('参数')]]
        for b in blocks:
            params='；'.join(f"{c.BLOCKS[b['kind']]['params'][k]['label']}={v}" for k,v in b['params'].items())
            rows.append([paragraph(c.BLOCKS[b['kind']]['label']),paragraph(params or '默认配置')])
        table=Table(rows,colWidths=[135,355],repeatRows=1);table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e3eafa')),('GRID',(0,0),(-1,-1),.3,colors.HexColor('#c7d4e8')),('VALIGN',(0,0),(-1,-1),'TOP')]))
        story.extend([table,Spacer(1,14),paragraph('接收结果与结论','heading')]);story.extend(paragraph(s) for s in f['summary'])
        comparisons=doc.get('comparisons') or {}
        if comparisons.get('branches'):
            story.append(paragraph('共享信道接收方案对照','heading'))
            for branch in comparisons['branches']:
                metrics=branch['result']['metrics'];story.append(paragraph(f"{branch['name']}：BER={metrics.get('ber',0) or 0:.5g}；EVM={metrics.get('evm_percent',0) or 0:.5g}%。"))
        rf_comparisons=doc.get('rfComparisons') or {}
        if rf_comparisons.get('variants'):
            story.append(paragraph('射频实验任务对照','heading'))
            for variant in rf_comparisons['variants']:
                m=variant['result']['metrics'];story.append(paragraph(f"{variant['name']}：BER={m['ber']:.5g}，EVM={m['evm_percent']:.5g}%，PAPR={m['papr_db']:.5g} dB，净信息速率={m['net_bit_rate']:.5g} bit/s。"))
        curves=doc.get('sweeps',[])
        for axis in dict.fromkeys(s.get('axis','参数') for s in curves):
            group=[s for s in curves if s.get('axis','参数')==axis and s['points']]
            if group: story.extend([paragraph('性能比较 · '+axis,'heading'),Curve(group)])
        for curve in curves:
            story.append(paragraph(f"{curve.get('name','扫描')}：令牌 {curve.get('token','')}；设置 {json.dumps(curve.get('settings',{}),ensure_ascii=False)}"))
        for item in f['selected_materials']:
            story.append(paragraph(item['title'],'heading'))
            if item['series'] or item['heatmap']: story.append(MaterialFigure(item))
            if item['rows']:
                headers=item['headers'];width=490/len(headers)
                rows=[[paragraph(value) for value in headers]]+[[paragraph('—' if value is None else f'{value:.5g}' if isinstance(value,float) else value) for value in row] for row in item['rows']]
                table=Table(rows,colWidths=[width]*len(headers),repeatRows=1)
                table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e3eafa')),('GRID',(0,0),(-1,-1),.3,colors.HexColor('#c7d4e8')),('VALIGN',(0,0),(-1,-1),'TOP')]))
                story.append(table)
            for text in (item['note'],item['caption']):
                if text: story.append(paragraph(text))
        if f['conclusion']: story.extend([paragraph('实验结论','heading'),paragraph(f['conclusion'])])
        story.extend([paragraph('复现信息','heading'),paragraph(f"随机种子 {doc['program']['seed']}；构建令牌 {f['build']['token']}。"),paragraph('误码统计保留实际试验帧数与置信区间；零错误点使用置信上界绘图。')])
        text=json.dumps({k:doc['program'][k] for k in ('sample_rate','sample_count','symbol_rate')},ensure_ascii=False);story.append(paragraph(text))
        def footer(canvas,document):
            canvas.setFont(font,8);canvas.setFillColor(colors.HexColor('#60718a'));canvas.drawString(52,25,'谛听 · 通信实验室');canvas.drawRightString(A4[0]-52,25,str(document.page))
        SimpleDocTemplate(output,pagesize=A4,leftMargin=52,rightMargin=52,topMargin=42,bottomMargin=43,title=doc['name'],author='通信实验室').build(story,onFirstPage=footer,onLaterPages=footer)
        return output.getvalue()
    finally: pdf_report.RENDER_LIMIT.release()
