"""Run browser -> gateway -> services -> MongoDB with explicit synthetic settings.

Never loads deployment env files. The disposable project is always removed unless
--keep is selected. 'both' verifies fixture behaviour then deepseek-r1:1.5b, with
controlled empty public retrieval in both modes. This is not a live-search test.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.request import build_opener, ProxyHandler
from urllib.error import HTTPError, URLError
from uuid import uuid4


ROOT=Path(__file__).resolve().parents[2]


def run(args):
    project='elo-career-flow-'+uuid4().hex[:8]
    env={name:os.environ[name] for name in ('PATH','TMPDIR') if name in os.environ}
    env.update({
        'APP_ENV':'development','AUTH_MODE':'local_test','COMPOSE_PROFILES':'development',
        'SMTP_HOST':'mailpit','SMTP_PORT':'1025','SMTP_SECURITY':'plain','SMTP_FROM':'no-reply@elo.test',
        'GOOGLE_CLIENT_ID':'test-client.apps.googleusercontent.com',
        'GATEWAY_PORT':str(args.port),'MAILPIT_PORT':str(args.mail_port),
        'AI_ENABLED':'true','CAREER_LLM_PROVIDER':'local','CAREER_LLM_RESPONSE_MODE':'json_schema_strict',
        'CAREER_LLM_TOKEN_PARAMETER':'max_tokens','AI_CONTEXT_TOKENS':'16384','AI_MAX_OUTPUT_TOKENS':'8192',
        'CAREER_LOCAL_TIMEOUT_SECONDS':'90','AI_RETRIES':'0',
        'CAREER_LLM_API_KEY':'','CAREER_RESEARCH_API_KEY':'','OPPORTUNITY_ENABLED':'true',
        'NEXT_TELEMETRY_DISABLED':'1',
        'PROFILE_E2E_BASE_URL':f'http://localhost:{args.port}',
        'MAILPIT_BASE_URL':f'http://localhost:{args.mail_port}',
        'CAREER_FLOW_E2E':'1','ELO_TEST_COMPOSE_PROJECT':project,
    })
    for name in ('MONGO_ROOT_PASSWORD','PROFILE_DB_PASSWORD','CAREER_DB_PASSWORD','CV_DB_PASSWORD','ASSESSMENT_DB_PASSWORD','ROADMAP_DB_PASSWORD'):
        env[name]='synthetic-career-flow-'+name.lower()
    compose=['docker','compose','--env-file','/dev/null','-p',project,
        '-f',str(ROOT/'infrastructure/docker/compose.yaml'),
        '-f',str(ROOT/'infrastructure/docker/compose.career-test.yaml')]
    def execute(command,*,cwd=ROOT):
        subprocess.run(command,cwd=cwd,env=env,check=True)
    opener=build_opener(ProxyHandler({}))
    def ready(path,expected):
        for _ in range(90):
            try:
                with opener.open(f'http://localhost:{args.port}'+path,timeout=3) as response:
                    if response.status==expected:return
            except HTTPError as error:
                if error.code==expected:return
            except (URLError,OSError):pass
            time.sleep(1)
        raise RuntimeError('Disposable test stack did not become ready.')
    modes=('fixture','local') if args.mode=='both' else (args.mode,)
    print(json.dumps({'project':project,'modes':modes,'gateway':args.port,'public_retrieval':'synthetic-empty'}),flush=True)
    try:
        for index,mode in enumerate(modes):
            env['CAREER_LLM_MODEL']='deepseek-r1:1.5b' if mode=='local' else 'synthetic-career-fixture'
            env['CAREER_LLM_BASE_URL']='http://host.docker.internal:11434/v1' if mode=='local' else 'http://127.0.0.1:8000/__synthetic__'
            env['CAREER_FLOW_LIVE']='1' if mode=='local' else '0'
            if index==0:
                execute([*compose,'up','--no-build' if args.no_build else '--build','-d'])
            else:
                execute([*compose,'up','--no-build','--no-deps','--force-recreate','-d','career-service'])
            ready('/api/v1/profile/auth-config',200)
            ready('/api/v1/career/workspace',401)
            if index==0 and not args.skip_boundary:
                with tempfile.TemporaryDirectory(prefix='elo-career-browser-') as directory:
                    config=Path(directory)/'playwright.config.mjs'
                    sdk=(ROOT/'node_modules/@playwright/test/index.mjs').as_uri()
                    config.write_text('import {defineConfig,devices} from '+json.dumps(sdk)+';\nexport default defineConfig('+json.dumps({
                        'testDir':str(ROOT/'apps/frontend/tests/e2e'),
                        'testMatch':['career-goal.spec.ts','career-overview.spec.ts','career-cv-confirmation.spec.ts','career-discovery.spec.ts','career-tools.spec.ts'],
                        'outputDir':str(ROOT/'apps/frontend/test-results/career-boundary'),
                        'workers':2,'retries':0,'reporter':'list',
                        'use':{'baseURL':env['PROFILE_E2E_BASE_URL'],'trace':'retain-on-failure','screenshot':'only-on-failure'},
                    })+');\n')
                    execute(['npx','--no-install','playwright','test','--config',str(config)],cwd=ROOT/'apps/frontend')
            print(json.dumps({'testing':mode,'model':env['CAREER_LLM_MODEL']}),flush=True)
            execute(['npx','--no-install','playwright','test','--config','playwright.integration.config.ts',
                '--output','test-results/career-flow/'+mode,'career-extraction-flow.spec.ts'],cwd=ROOT/'apps/frontend')
    except BaseException:
        subprocess.run([*compose,'logs','--tail=80','career-service'],cwd=ROOT,env=env,check=False)
        raise
    finally:
        if args.keep:print('Retained disposable project: '+project,flush=True)
        else:subprocess.run([*compose,'down','--volumes','--remove-orphans'],cwd=ROOT,env=env,check=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('fixture','local','both'),default='both')
    parser.add_argument('--port',type=int,default=8093)
    parser.add_argument('--mail-port',type=int,default=8036)
    parser.add_argument('--no-build',action='store_true',help='Use the previously built verification images.')
    parser.add_argument('--skip-boundary',action='store_true',help='Run only the real-service journey.')
    parser.add_argument('--keep',action='store_true',help='Retain this isolated project for diagnosis.')
    run(parser.parse_args())
