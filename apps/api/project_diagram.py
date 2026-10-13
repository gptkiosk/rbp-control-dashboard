"""Render reviewed project data to bounded, portable PNG pages; no external service."""
from pathlib import Path
import textwrap
from PIL import Image,ImageDraw,ImageFont

def render(project,document,data_dir):
    root=Path(data_dir)/'diagrams';root.mkdir(mode=0o700,exist_ok=True)
    font_path=next((p for p in ('/System/Library/Fonts/Supplemental/Arial.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf') if Path(p).is_file()),None)
    font=lambda size:ImageFont.truetype(font_path,size) if font_path else ImageFont.load_default(size=size)
    phases={n['key']:n['title'] for n in document['nodes'] if n['kind']=='phase'}
    nodes=[n for n in document['nodes'] if n['kind']=='story']
    indices={n['key']:i+1 for i,n in enumerate(nodes)}
    files=[]
    for page,start in enumerate(range(0,len(nodes),12),1):
        batch=nodes[start:start+12];rows=(len(batch)+1)//2
        image=Image.new('RGB',(1500,210+rows*265),(239,246,255));draw=ImageDraw.Draw(image)
        draw.text((40,28),textwrap.shorten(document['title'],width=68,placeholder='…'),font=font(30),fill='#183c65')
        draw.text((40,76),f'Project #{project.id} · revision {project.revision} · page {page}/{(len(nodes)+11)//12}',font=font(20),fill='#405f80')
        draw.text((40,112),'Prerequisites use story numbers. Review scope and definition of done in MCD or with Hermes.',font=font(18),fill='#405f80')
        positions={n['key']:(40+(i%2)*740,175+(i//2)*265) for i,n in enumerate(batch)}
        for n in batch:
            x,y=positions[n['key']]
            for dep in n['depends_on']:
                if dep in positions:
                    dx,dy=positions[dep]
                    # Dependency links stay in the gutters; numbers also remain explicit.
                    draw.line([(dx+345,dy+230),(dx+345,dy+245),(x+345,y-12),(x+345,y)],fill='#6b91ba',width=3)
                    draw.polygon([(x+338,y-9),(x+352,y-9),(x+345,y)],fill='#6b91ba')
        for n in batch:
            x,y=positions[n['key']];draw.rounded_rectangle((x,y,x+690,y+230),radius=18,fill='white',outline='#86acd4',width=2)
            title=f"{indices[n['key']]}. {n['title']}"
            draw.multiline_text((x+20,y+15),'\n'.join(textwrap.wrap(title,44)[:2]),font=font(24),fill='#183c65',spacing=4)
            details=[phases.get(n['parent'],'Project root'),n['assignee']+' · '+(n['model'] or 'configured default'),
                'Target: '+(n['agent_target'] or 'default') if n['assignee']=='openclaw' else 'Mode: '+n['mode'],
                'Requires: '+(', '.join(str(indices[k]) for k in n['depends_on']) or 'none')]
            lines=[line for item in details for line in textwrap.wrap(item,65)[:2]]
            draw.multiline_text((x+20,y+92),'\n'.join(lines[:5])+(' …' if len(lines)>5 else ''),font=font(18),fill='#405f80',spacing=5)
        path=root/f'project-{project.id}-r{project.revision}-page{page}.png';image.save(path);path.chmod(0o600);files.append(str(path))
    return files
