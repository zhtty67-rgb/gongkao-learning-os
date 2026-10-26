import argparse,json,sys
from pathlib import Path
sys.path.insert(0,'D:/gong/gongkao-learning-os')
from backend.app.domain.module_teacher_service import ModuleTeacherService
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--out');args=ap.parse_args()
 payload=json.loads(Path(args.input).read_text('utf-8'))
 report=ModuleTeacherService().explain_question('teacher_longfei',payload)['report_markdown']
 if args.out:Path(args.out).write_text(report,encoding='utf-8')
 else:print(report)
