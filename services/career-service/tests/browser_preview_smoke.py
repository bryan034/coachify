"""Explicit real-Chromium smoke check with synthetic HTTP responses; no external network.

Run with browser binaries installed, outside the normal pytest discovery.
"""
import io
import json
import sys
from contextlib import redirect_stdout
from unittest.mock import patch
from app.clients import job_url
from app.workers import browser_preview


def main():
    url='https://synthetic.test/job'
    calls=[]
    job={'@type':'JobPosting','title':'Synthetic analyst',
        'description':'<p>Analyse product data with SQL and communicate research findings.</p>'}
    script=('const s=document.createElement("script");s.type="application/ld+json";s.textContent='
        +json.dumps(json.dumps(job))+';document.head.appendChild(s);document.body.innerHTML="<main>Synthetic analyst</main>";')
    def fetch(target,deadline):
        calls.append(target)
        if target.endswith('/robots.txt'):return 404,{},b''
        if target.endswith('/app.js'):return 200,{'content-type':'application/javascript'},script.encode()
        assert target==url,target
        return 200,{'content-type':'text/html'},b'<html><head></head><body><div id="root"></div><script src="/app.js"></script></body></html>'
    output=io.StringIO()
    # The worker imports the browser module after these patches; the renderer's
    # real sandbox, limits and Chromium execution remain enabled.
    with patch.object(job_url,'request_page',fetch),patch('socket.getaddrinfo',lambda *a,**kw:[(2,1,6,'',('93.184.216.34',443))]),patch.object(sys,'argv',['browser_preview','20']),patch.object(sys,'stdin',io.TextIOWrapper(io.BytesIO(url.encode()))),redirect_stdout(output):
        browser_preview.main()
    result=json.loads(output.getvalue())
    assert 'preview' in result,result
    assert 'SQL' in result['preview']['text'] and result['preview']['source_url']==url,result
    assert calls==['https://synthetic.test/robots.txt',url,'https://synthetic.test/app.js'],calls
    print('Real sandboxed browser worker: synthetic JavaScript extraction passed.')


if __name__=='__main__':main()
