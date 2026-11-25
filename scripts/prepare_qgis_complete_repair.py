#!/usr/bin/env python3
"""Repair audited XML nodes only, preserving all unrelated bytes."""
import collections,json,pathlib,re,sys
from xml.sax.saxutils import escape
from xml.parsers import expat
from lxml import etree as E

source,output,inventory,variants_dir=map(pathlib.Path,sys.argv[1:5])
variants={p.parent.name.removeprefix('schema-'):json.loads(p.read_text()) for p in variants_dir.glob('*/schema-variant.json')}
assert set(variants)=={'standard','agxx','webgis'}
rows=json.loads(inventory.read_text())['review']
raw=source.read_bytes()
root=E.parse(str(source)); layers={l.findtext('id'):l for l in root.xpath('//projectlayers/maplayer')}
parser=expat.ParserCreate(); iterator=iter(n for n in root.getroot().iter() if isinstance(n.tag,str)); positions={}; stack=[]
def tag_end(i):
    quote=None
    while i<len(raw):
        c=raw[i]
        if quote is not None:
            if c==quote:quote=None
        elif c in (34,39):quote=c
        elif c==62:return i+1
        i+=1
    raise AssertionError('unterminated tag')
def start(tag,attrs):
    node=next(iterator);i=parser.CurrentByteIndex;j=tag_end(i)
    assert node.tag.rsplit('}',1)[-1]==tag.split(':')[-1],(node.tag,tag)
    stack.append((node,i,j))
def end(tag):
    node,i,j=stack.pop();k=j if raw[i:j].rstrip().endswith(b'/>') else tag_end(parser.CurrentByteIndex)
    positions[node]=(i,j,k)
parser.StartElementHandler=start;parser.EndElementHandler=end;parser.Parse(raw,True)
assert next(iterator,None) is None and not stack
changes=[]; edits={}
def record(row,action,target=None,**extra):
    changes.append(dict(category=row['category'],layer=row['layer'],style=row['style'],layer_style=row['layer_style'],field=row['field'],action=action,target=target,**extra))
def scope(row):
    lid,style=row['layer_style'].rsplit('|',1);l=layers[lid];m=l.find('map-layer-style-manager')
    if m is None or style==m.get('current'):return l
    return m.xpath('./map-layer-style[@name=$s]/qgis',s=style)[0]
def available(row,name):
    return [v for v,d in variants.items() if name in d['fields'].get(row['layer_style'],[])]
def replace_attr(node,key,value):
    i,j,k=positions[node];line=edits.get((i,j),raw[i:j]).decode('utf-8')
    pattern=r'(?<![\w-])'+re.escape(key)+r'="[^"]*"'
    val=escape(str(value),{'"':'&quot;','\n':'&#xa;','\r':'&#xd;','\t':'&#x9;'})
    line,n=re.subn(pattern,lambda m:key+'="'+val+'"',line,count=1);assert n==1,(key,i);edits[i,j]=line.encode('utf-8')
def remove(node):
    i,j,k=positions[node];a=raw.rfind(b'\n',0,i)+1;b=raw.find(b'\n',k)
    if b>=0 and not raw[a:i].strip() and not raw[k:b].strip():i,k=a,b+1
    assert (i,k) not in edits;edits[i,k]=b''

a=[f'ag{v}_{n}' for v in (64,96) for n in ('remark','fk_provider','last_modification')]
M={'vw_tww_overflow':{**{n:'pu_'+n for n in ('construction_type','operating_point','stop_level','start_level','pump_flow_min_single','pump_flow_max_single','placement_of_pump','placement_of_actuation')},**{n:'pw_'+n for n in ('hydraulic_overflow_length','level_max','level_min','weir_edge','weir_kind')},**{n:'lw_'+n for n in ('length','width','opening_shape')},**{n:'ov_'+n for n in a}},'vw_tww_reach':{n:'ne_'+n for n in a},'vw_tww_wastewater_structure':{'ag96_fk_measure':'ws_ag96_fk_measure','wn_ag64_last_modification':'ne_ag64_last_modification','wn_ag96_last_modification':'ne_ag96_last_modification'},'vw_tww_wastewater_node':{'backflow_level':'backflow_level_current'},'mvw_tww_channel':{'_from_node':'_from_ne','_to_node':'_to_ne','length_effective':'_re_length_effective'},'vw_tww_channel_maintenance':{'_from_node':'_from_ne','_to_node':'_to_ne'},'vw_tww_log_card':{'vw_tww_wastewater_structure_ma_function':'ma_function','vw_tww_wastewater_structure_ss_function':'ss_function'}}
for layer in ('vw_tww_channel_maintenance','vw_tww_ws_maintenance'):
    M.setdefault(layer,{}).update({n:'me_'+n for n in ('base_data','data_details','fk_operating_company','last_modification','operator','reason','result','status','time_point')})
M['vw_tww_catchment_area']={n:'_'+n.lower() for n in ('Fred_rw_current','Fred_rw_planned','Fred_ww_current','Fred_ww_planned','Population_current','Population_planned')}
retired={'measuring_point':{'fk_reference_station'},'vw_tww_wastewater_structure':{'_input_label','_output_label'}}
# The preceding eight-site patch is already applied to source.
for row in rows:
    cat=row['category'];old=row['field'];s=scope(row);name=row['layer'];new=M.get(name,{}).get(old)
    if cat not in ('C2','C5'):continue
    if row.get('available_in'):
        record(row,'preserve_supported_extension',available_in=row['available_in']);continue
    assert not available(row,old),(name,old)
    if cat=='C2':
        nodes=s.xpath('./attributeEditorForm//attributeEditorField[@name=$n]',n=old)
        if not nodes:
            assert name=='measuring_point' or old in ('_from_node','_to_node'),row
            record(row,'already_repaired',new);continue
        if new:
            assert available(row,new),(name,old,new)
            target=s.xpath('./attributeEditorForm//attributeEditorField[@name=$n]',n=new)
            for node in nodes:
                if target:remove(node)
                else:
                    replace_attr(node,'name',new)
                    # QGIS resolves by field name when the project is loaded.
                    replace_attr(node,'index',-1)
            record(row,'remove_duplicate' if target else 'rename_form',new)
        else:
            assert old in retired.get(name,set()),row
            for node in nodes:remove(node)
            record(row,'remove_retired_form')
    else:
        if new and not available(row,new):new=None
        counts=collections.Counter()
        for tag in ('editable','labelOnTop','reuseLastValue','reuseLastValuePolicy'):
            targets=s.xpath('./'+tag+'/field[@name=$n]',n=new) if new else []
            for node in s.xpath('./'+tag+'/field[@name=$n]',n=old):
                if new and not targets:
                    # Existing default-style settings are authoritative for shared fields.
                    # Never revive an old automatic input reuse policy on hydraulic data.
                    lid,style=row['layer_style'].rsplit('|',1)
                    base=layers[lid]
                    canonical=base.xpath('./'+tag+'/field[@name=$n]',n=new) if s is not base else []
                    replace_attr(node,'name',new)
                    if canonical:
                        for attr,value in canonical[0].attrib.items():
                            if attr!='name' and attr in node.attrib and node.get(attr)!=value:
                                replace_attr(node,attr,value)
                    counts['migrated']+=1
                else:
                    remove(node);counts['kept_current_target' if targets else 'removed_unresolved']+=1
        assert sum(counts.values()),row
        record(row,'migrate_or_remove_obsolete_options',new,**counts)
# Preserve documented identifier + status convention. Codes follow the
# catchment view joins; label column follows hydraulic_char_data's widget.
for row in rows:
    cat=row['category'];s=scope(row);field=row['field']
    if cat=='C3':
        status={'hc_c_identifier':6372,'hc_o_identifier':6373,'hc_p_identifier':6371}[field]
        node=s.xpath('./defaults/default[@field=$f]',f=field)[0]
        assert node.get('expression')==row['expression']
        base='coalesce(attribute(get_feature(\'vw_tww_log_card\',\'obj_id\',"fk_log_card"),\'identifier\'),attribute(get_feature(\'vw_tww_wastewater_node\',\'obj_id\',"wn_obj_id"),\'identifier\'))'
        label=f"attribute(get_feature('hydraulic_char_data_status','code',{status}),'value_en')"
        expr=f"left({base} || '-' || {label},20)"
        replace_attr(node,'expression',expr);record(row,'repair_default',expr,status_code=status)
    elif cat=='C4':
        node=s.xpath('./constraintExpressions/constraint[@field=$f]',f=field)[0]
        assert node.get('exp')==row['expression'];prefix=field.removesuffix('pump_flow_min')
        expr=node.get('exp').replace('"pump_flow_max"','"'+prefix+'pump_flow_max"').replace('"pump_flow_min"','"'+prefix+'pump_flow_min"')
        replace_attr(node,'exp',expr);record(row,'repair_constraint',expr)
    elif cat=='C1':record(row,'already_repaired')
pieces=[];last=0
for (i,j),value in sorted(edits.items()):
    assert i>=last,(i,j,last)
    pieces.extend((raw[last:i],value));last=j
pieces.append(raw[last:]);output.write_bytes(b''.join(pieces))
parsed=E.parse(str(output));assert len(parsed.xpath('//projectlayers/maplayer'))==len(layers)
assert len(changes)==len(rows),(len(changes),len(rows))
report={'changes':changes,'counts':dict(collections.Counter((r['category']+' '+r['action']) for r in changes)),'xml_spans_modified':len(edits)}
output.with_suffix('.review.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report['counts'],indent=2));print('XML_SPANS_CHANGED',len(edits));print('COMPLETE_REPAIR_READY')
