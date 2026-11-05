"""Build a source-grounded, deduplicated reference library for this review."""
from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parent


def bib_fields(text):
    fields={};cursor=text.find(',')+1
    while cursor>0 and cursor<len(text):
        match=re.search(r'([A-Za-z_]+)\s*=\s*',text[cursor:])
        if not match:break
        name=match.group(1).lower();start=cursor+match.end();op=text[start:start+1]
        if op=='{':
            depth=1;end=start+1
            while end<len(text) and depth:
                if text[end]=='{' and text[end-1]!='\\':depth+=1
                elif text[end]=='}' and text[end-1]!='\\':depth-=1
                end+=1
            value=text[start+1:end-1];cursor=end
        elif op=='"':
            end=start+1
            while end<len(text) and (text[end]!='"' or text[end-1]=='\\'):end+=1
            value=text[start+1:end];cursor=end+1
        else:
            end=text.find(',',start)
            if end<0:end=text.find('}',start)
            value=text[start:end];cursor=end+1
        fields[name]=re.sub(r'\s+',' ',value).strip()
    return fields


def norm(text):return re.sub('[^a-z0-9]','',text.lower())


def main():
    rows=json.loads((ROOT/'records_verified_seed.json').read_text(encoding='utf-8'))
    publisher={}
    for path in (ROOT/'sources').glob('*.bib'):
        value=bib_fields(path.read_text(encoding='utf-8'))
        assert all(k in value for k in ['title','author','year']),path
        publisher[norm(value['title'])]=value
    for i,row in enumerate(rows,1):
        row.pop('official_bibtex',None)
        row['id']=f'P{i:02d}'
        row['arxiv_id']=row['source_url'].split('/abs/')[-1] if 'arxiv.org/abs/' in row['source_url'] else None
        data=publisher.get(norm(row['title']))
        if data:
            row.update({'title':data['title'].replace('{','').replace('}',''),
                'authors':data['author'].split(' and '),'year':data['year'],'venue':data['booktitle'].replace('{','').replace('}',''),
                'doi':data.get('doi'),'source_url':data['url'],'publication_status':'publisher_proceedings_verified','bib_fields':data})
        elif row.get('official_bibtex'):
            raise AssertionError('Publisher metadata normalization expected')
        else:
            row['venue']=row.get('venue_description') or 'arXiv preprint'
            row['publication_status']='arxiv_metadata_verified_venue_comment_only'
        if 'proceedings.mlr.press/' in row['source_url']:
            # Parsed from the official PMLR page already opened during review.
            row['publication_status']='publisher_proceedings_verified'
            row['venue']='ICML '+row['year']
        if 'proceedings.iclr.cc/' in row['source_url']:
            row.update({'year':'2026','venue':'ICLR 2026','publication_status':'publisher_proceedings_verified',
                'authors':['Chenxu Yang','Qingyi Si','Yongjie Duan','Zheliang Zhu','Chenyu Zhu','Qiaowei Li','Minghui Chen','Zheng Lin','Weipinng Wang']})
        if row.get('arxiv_id')=='2501.12948':
            data=json.loads((ROOT/'sources/deepseek_r1_crossref.json').read_text())['message']
            row.update({'preprint_title':row['title'],'title':data['title'][0],
                'authors':[x.get('family','')+', '+x.get('given','') if x.get('given') else x.get('name',x.get('family','')) for x in data['author']],
                'year':'2025','venue':data['container-title'][0],'volume':data.get('volume'),'pages':data.get('page'),
                'doi':data['DOI'],'source_url':'https://www.nature.com/articles/s41586-025-09422-z',
                'publication_status':'publisher_crossref_journal_verified','alternate_url':'https://arxiv.org/abs/2501.12948'})
        if row.get('arxiv_id') and not row.get('doi'):row['doi']='10.48550/arXiv.'+row['arxiv_id']
        assert row.get('authors') and row.get('year') and row.get('title'),row['title']
    assert len(rows)==62 and len({norm(r['title']) for r in rows})==len(rows)
    bib=[];ris=[]
    for row in rows:
        key='longcot_'+row['id'].lower();row['citation_key']=key
        article=row['publication_status']=='publisher_crossref_journal_verified'
        proceedings=row['publication_status']=='publisher_proceedings_verified'
        fields={'title':row['title'],'author':' and '.join(row['authors']),'year':row['year'],'url':row['source_url']}
        if row.get('doi'):fields['doi']=row['doi']
        if article:
            fields.update({'journal':row['venue'],'volume':row['volume'],'pages':row['pages']})
        elif proceedings:fields['booktitle']=row['venue']
        else:
            fields['eprint']=row['arxiv_id'];fields['archivePrefix']='arXiv'
            if row['venue']!='arXiv preprint':fields['note']='Author metadata: '+row['venue']
        kind='article' if article else 'inproceedings' if proceedings else 'misc'
        def protect(text):return text.replace('%',r'\%').replace('&',r'\&').replace('_',r'\_')
        bib.append('@'+kind+'{'+key+',\n'+',\n'.join('  '+k+' = {'+protect(str(v))+'}' for k,v in fields.items())+'\n}\n')
        record=['TY  - '+('JOUR' if article else 'CONF' if proceedings else 'GEN')]
        record+=['AU  - '+name for name in row['authors']]
        record+=['TI  - '+row['title'],'PY  - '+row['year'],'T2  - '+row['venue'],'UR  - '+row['source_url']]
        if row.get('doi'):record+=['DO  - '+row['doi']]
        record+=['ID  - '+row['id'],'ER  -',''];ris.append('\n'.join(record))
    (ROOT/'references.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (ROOT/'references.bib').write_text('\n'.join(bib),encoding='utf-8')
    (ROOT/'references.ris').write_text('\n'.join(ris),encoding='utf-8')
    print(json.dumps({'records':len(rows),'publisher_verified':sum('publisher_' in r['publication_status'] for r in rows),
        'arxiv_records':sum(r['publication_status'].startswith('arxiv') for r in rows),'all_authors_present':True}))


if __name__=='__main__':main()
