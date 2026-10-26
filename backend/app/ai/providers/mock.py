"""Mock model provider for offline testing and deterministic simulation."""
import json
from typing import Any

from ..schemas import Message, ModelPolicyConfig, ProviderUnavailableError


class MockModelProvider:
    """Deterministic mock provider that simulates LLM generation with valid structured JSON."""

    provider_name: str = 'mock'

    def __init__(self, canned_response: str | None = None, simulate_failure: bool = False):
        self.canned_response = canned_response
        self.simulate_failure = simulate_failure

    async def generate(
        self,
        messages: list[Message],
        config: ModelPolicyConfig,
        json_mode: bool = False,
    ) -> tuple[str, dict[str, int]]:
        if self.simulate_failure:
            raise ProviderUnavailableError('Simulated mock provider failure')

        if self.canned_response is not None:
            return self.canned_response, {'prompt_tokens': 50, 'completion_tokens': 30, 'total_tokens': 80}

        # Analyze message content to generate context-appropriate mock outputs
        full_prompt = ' '.join(m.content for m in messages)
        prompt_lower = full_prompt.lower()
        # The schema is explicit; incidental words in past dialogue are not task markers.
        schema_name = None
        for message in messages:
            marker='You MUST reply with valid JSON conforming to this schema:\n'
            if message.role=='system' and marker in message.content:
                try: schema_name=json.loads(message.content.rsplit(marker,1)[1]).get('title')
                except (ValueError,TypeError): pass
        if schema_name=='CoachChoice':
            return json.dumps({'focus': 'task'}), {'total_tokens': 20}
        if schema_name=='PointMappingOutput':
            # Offline simulation: quote actual supplied text, never invent spans.
            payload = json.loads(messages[-1].content)
            para = payload['paragraphs'][0]
            answer = payload['answer']
            matches = [{'point_id': p['id'], 'status': 'partial', 'paragraph_id': para['id'],
                        'material_quote': para['text'], 'student_quote': answer,
                        'error_type': 'precision'} for p in payload['points']]
            return json.dumps({'matches': matches}, ensure_ascii=False), {'total_tokens': 100}
        if schema_name=='InitialDiagnosisInference':
            data={'can_conclude_now':False,'hypotheses':[{'hypothesis_id':'mock-h1','stage_code':'calc_accuracy',
                'label':'核对比较基准','rationale':'模拟诊断：尚无完整思路，需要核实基期与现期。','missing_info':'分母选择的理由'}],
                'clarification_question':'你计算增长率时用的是基期量还是现期量？',
                'clarification_options':['基期量','现期量'],'suggested_remedy':'模拟建议：先说明比较基准，再核对公式。'}
            return json.dumps(data,ensure_ascii=False),{'total_tokens':100}
        if schema_name=='ShenlunAssessmentOutput':
            data={'coverage':0.85,'abstraction':0.8,'precision':0.78,'structure':0.9,'conciseness':0.82,
                'overall_score':83.5,'missing_points':['模拟：需要补充原因分析'],'redundant_points':[],
                'weak_abstractions':[],'wording_issues':[],'next_action':'模拟评价：核对材料依据并改写一版。'}
            return json.dumps(data,ensure_ascii=False),{'total_tokens':100}
        if schema_name=='StepExplanationSchema':
            data={'knowledge_node':'资料分析 > 增长率','given_and_target':'基期量120万册，现期量150万册，求增长率。',
                'method_name':'增长率公式','derivation_steps':['增长量=150-120=30。','增长率=30/120=25%。'],
                'answer_verification':'25%对应选项B。','attempt_check_point':'模拟讲解：核对分母使用基期量。'}
            return json.dumps(data,ensure_ascii=False),{'total_tokens':100}

        if 'ADAPTIVE_MICRO_LESSON' in full_prompt:
            payload=json.loads(messages[-1].content)
            example=payload['verified_example']
            data={'core_concept':payload['node']['name']+'：先明确基准、适用条件与数量关系。',
                  'example':example['stem']+'\n'+example['explanation']}
            return json.dumps(data,ensure_ascii=False),{'total_tokens':100}
        if 'ADAPTIVE_CHECK_ASSESSOR' in full_prompt:
            payload=json.loads(messages[-1].content)
            answer=payload['raw_answer']
            # Offline demonstration only; orchestrator excludes mock assessments from statistics.
            correct=any(k in answer for k in ['基期量','增长率','逆否','效率相加','应用正确']) and '不会' not in answer
            missing=payload['prerequisites'][0]['id'] if payload['prerequisites'] and '基期' in answer and not correct else None
            data={'correct':correct,'confidence':0.9,'feedback':'模拟评估：依据回答中的方法说明判定，不能作为真实学习效果证据。',
                  'failure_kind':'none' if correct else ('prerequisite_gap' if missing else 'current_node'),
                  'missing_skill_id':missing,'error_type':'unknown'}
            return json.dumps(data,ensure_ascii=False),{'total_tokens':100}

        if 'hint_level' in prompt_lower or '启发提示' in full_prompt or '提示等级' in full_prompt:
            # Generate structured hint
            requested_level = 1
            for level in (4, 3, 2, 1):
                if f'level_{level}' in prompt_lower or f'level {level}' in prompt_lower or f'level:{level}' in prompt_lower:
                    requested_level = level
                    break

            hint_data = {
                'hint_level': requested_level,
                'direction': '注意题目中给出的时间与核心关联词。' if requested_level >= 1 else '',
                'method': '使用基期量与增长率公式计算：增长率 = (现期量 − 基期量) ÷ 基期量。' if requested_level >= 2 else '',
                'partial_step': '先计算第一步的增长量，再代入第二步求解。' if requested_level >= 3 else '',
                'full_explanation': '本题考查核心概念，选项 A 为唯一正解。' if requested_level >= 4 else '',
                'message': f'第 {requested_level} 级启发提示已生成。',
            }
            import re
            m_ids = re.findall(r'\[EVIDENCE:\s*([a-zA-Z0-9_\-]+)\]', full_prompt)
            real_ids = [m for m in m_ids if m != '{id}']
            chosen_id = None
            chosen_snip = ''
            if real_ids:
                for cid in real_ids:
                    snip_m = re.search(rf'\[EVIDENCE:\s*{re.escape(cid)}\].*?内容片段：\s*([^\n]+)', full_prompt, re.DOTALL)
                    if snip_m and any(k in snip_m.group(1) for k in ['基期量', '增长率', '工程', '方程', '未知数']):
                        chosen_id = cid
                        chosen_snip = snip_m.group(1).strip()
                        break
                if chosen_id is None:
                    chosen_id = real_ids[-1]
                    snip_m = re.search(rf'\[EVIDENCE:\s*{re.escape(chosen_id)}\].*?内容片段：\s*([^\n]+)', full_prompt, re.DOTALL)
                    if snip_m:
                        chosen_snip = snip_m.group(1).strip()
                chosen_evidence_id = chosen_id
                hint_data['adopted_evidence_id'] = chosen_evidence_id
                hint_data['citation'] = chosen_evidence_id
                if chosen_snip:
                    hint_data['method'] = (
                        f"使用基期量与增长率公式计算：增长率 = (现期量 − 基期量) ÷ 基期量。"
                        f"依据所引资料数据「{chosen_snip[:60]}」进行推导。"
                    )
            elif re.search(r'依据出处：([^\n]+)', full_prompt):
                hint_data['citation'] = re.search(r'依据出处：([^\n]+)', full_prompt).group(1).strip()

            return json.dumps(hint_data, ensure_ascii=False), {'prompt_tokens': 60, 'completion_tokens': 40, 'total_tokens': 100}

        elif 'tutor_followup' in prompt_lower or '追问' in full_prompt or '答疑' in full_prompt:
            followup_reply = (
                '【AI 助教解答】：针对你的疑问，核心在于理清题目的破局点与选项陷阱。\n'
                '1. **关键条件分析**：审题时需注意题目所给的前提限定词。\n'
                '2. **选项辨析**：排除干扰项时，可以结合公式进行代入反推。\n'
                '3. **解题建议**：日常练习中注意此类同义替换与速算特征。'
            )
            import re
            m_ids = re.findall(r'\[EVIDENCE:\s*([a-zA-Z0-9_\-]+)\]', full_prompt)
            real_ids = [m for m in m_ids if m != '{id}']
            if real_ids:
                followup_reply += f'\n\n[ADOPT_EVIDENCE: {real_ids[0]}]\n本题解法依据 [EVIDENCE: {real_ids[0]}] 中的核心公式与方法，根据工作总量与效率关系公式进行计算。'

            if json_mode:
                return json.dumps({'reply': followup_reply}, ensure_ascii=False), {'prompt_tokens': 60, 'completion_tokens': 40, 'total_tokens': 100}
            return followup_reply, {'prompt_tokens': 60, 'completion_tokens': 40, 'total_tokens': 100}

        elif 'error_diagnosis' in prompt_lower or '客观诊断' in full_prompt:
            diagnosis_data = {
                'error_type': 'method_selection',
                'confidence': 0.88,
                'cause': '审题时混淆了现期比重与基期比重的计算方法。',
                'recommended_intervention': '巩固公式推导并进行变式题训练。',
            }
            import re
            m_ids = re.findall(r'\[EVIDENCE:\s*([a-zA-Z0-9_\-]+)\]', full_prompt)
            real_ids = [m for m in m_ids if m != '{id}']
            chosen_id = None
            if real_ids:
                for cid in real_ids:
                    snip_m = re.search(rf'\[EVIDENCE:\s*{re.escape(cid)}\].*?内容片段：\s*([^\n]+)', full_prompt, re.DOTALL)
                    if snip_m and any(k in snip_m.group(1) for k in ['基期量', '增长率', '工程', '方程', '未知数']):
                        chosen_id = cid
                        break
                chosen_evidence_id = chosen_id or real_ids[-1]
                diagnosis_data['adopted_evidence_id'] = chosen_evidence_id
                diagnosis_data['citation'] = chosen_evidence_id
            elif re.search(r'依据出处：([^\n]+)', full_prompt):
                diagnosis_data['citation'] = re.search(r'依据出处：([^\n]+)', full_prompt).group(1).strip()

            return json.dumps(diagnosis_data, ensure_ascii=False), {'prompt_tokens': 80, 'completion_tokens': 50, 'total_tokens': 130}

        elif '分步精讲' in full_prompt:
            # New unified step-explanation flow (interactive_assessor).
            # Fields must exactly match StepExplanationSchema (StrictModel forbids extras).
            explanation_data = {
                'knowledge_node': '资料分析 > 增长率与增长量',
                'given_and_target': '已知基期量120万册、现期量150万册，求今年的同比增长率。',
                'method_name': '增长率公式',
                'derivation_steps': [
                    '第 1 步：求增长量：150 - 120 = 30（万册）。',
                    '第 2 步：以基期量为分母：30 / 120 = 0.25，即25%。',
                ],
                'answer_verification': '增长率25%与选项B一致。',
                'attempt_check_point': '核对分母使用的是基期量（去年），不要代成现期量。',
            }
            return json.dumps(explanation_data, ensure_ascii=False), {'prompt_tokens': 90, 'completion_tokens': 60, 'total_tokens': 150}

        elif 'tutor_explanation' in prompt_lower or '深度复盘' in full_prompt or '深度解析' in full_prompt:
            # Legacy deep-dive flow (tutor.generate_explanation, TutorExplanationOutput).
            explanation_data = {
                'summary': '本题考查核心知识点，审题需关注基准期与比例关系。',
                'core_concept': '掌握定义公式并熟记常用速算技巧，通过基期量与增长率公式解题。',
                'step_by_step': [
                    '第 1 步：从题干提取已知数据与求解目标。',
                    '第 2 步：列出标准计算算式。',
                    '第 3 步：结合选项差距选用合理的截位直除法。',
                ],
                'common_pitfalls': [
                    '误将现期量代入分母。',
                    '忽略了百分号转化导致的量级偏差。',
                ],
                'recommended_action': '建议完成 3 道同考点变式练习以加深记忆。',
            }
            import re
            m_ids = re.findall(r'\[EVIDENCE:\s*([a-zA-Z0-9_\-]+)\]', full_prompt)
            real_ids = [m for m in m_ids if m != '{id}']
            chosen_id = None
            if real_ids:
                for cid in real_ids:
                    snip_m = re.search(rf'\[EVIDENCE:\s*{re.escape(cid)}\].*?内容片段：\s*([^\n]+)', full_prompt, re.DOTALL)
                    if snip_m and any(k in snip_m.group(1) for k in ['基期量', '增长率', '工程', '方程', '未知数']):
                        chosen_id = cid
                        break
                chosen_evidence_id = chosen_id or real_ids[-1]
                explanation_data['adopted_evidence_id'] = chosen_evidence_id
                explanation_data['citation'] = chosen_evidence_id
            elif re.search(r'依据出处：([^\n]+)', full_prompt):
                explanation_data['citation'] = re.search(r'依据出处：([^\n]+)', full_prompt).group(1).strip()

            return json.dumps(explanation_data, ensure_ascii=False), {'prompt_tokens': 90, 'completion_tokens': 60, 'total_tokens': 150}

        elif 'shenlun_assessment' in prompt_lower or '五维诊断评分' in full_prompt:
            assessment_data = {
                'coverage': 0.85,
                'abstraction': 0.80,
                'precision': 0.78,
                'structure': 0.90,
                'conciseness': 0.82,
                'overall_score': 83.5,
                'missing_points': ['对“网点撤并后办事不便”的原因分析稍显不足。'],
                'redundant_points': ['重复提及了村干部的具体身份细节。'],
                'weak_abstractions': ['可将“手把手教老人使用”提升为“消除数字鸿沟与适老服务”。'],
                'wording_issues': ['个别语句存在口语化转述。'],
                'next_action': '在第二轮修改中加强动宾搭配，紧扣“问题-举措”对照结构归纳作答。',
            }
            return json.dumps(assessment_data, ensure_ascii=False), {'prompt_tokens': 120, 'completion_tokens': 80, 'total_tokens': 200}

        elif 'primary_knowledge_node_code' in prompt_lower or 'knowledge classification' in prompt_lower:
            # Extract candidate codes from the prompt
            import re
            cand_matches = re.findall(r'"code":\s*"([^"]+)"', full_prompt)
            chosen = None
            for code in cand_matches:
                key = code.split('.')[-1]
                if key in ('conditional_logic', 'logic') and any(w in full_prompt for w in ('充分条件', '必要条件', '只要', '只有')):
                    chosen = code; break
                elif key in ('definition',) and any(w in full_prompt for w in ('定义', '根据上述定义')):
                    chosen = code; break
                elif key in ('analogy',) and any(w in full_prompt for w in ('类比', '相当于', '：')):
                    chosen = code; break
                elif key in ('graphic',) and any(w in full_prompt for w in ('图形', '问号处', '规律')):
                    chosen = code; break
                elif key in ('base',) and any(w in full_prompt for w in ('基期', '上年同期', '2022年该省轻工业', '2022年该市民营企业')):
                    chosen = code; break
                elif key in ('interval',) and any(w in full_prompt for w in ('间隔', '隔年')):
                    chosen = code; break
                elif key in ('two_period',) and any(w in full_prompt for w in ('两期比重', '比重约')):
                    chosen = code; break
                elif key in ('mixed',) and any(w in full_prompt for w in ('混合', '偏向')):
                    chosen = code; break
                elif key in ('law',) and any(w in full_prompt for w in ('民法典', '行政处罚法', '失踪人', '行政处罚')):
                    chosen = code; break
                elif key in ('politics',) and any(w in full_prompt for w in ('政治', '根本任务', '社会主义现代化建设')):
                    chosen = code; break
                elif key in ('work_problem', 'work') and any(w in full_prompt for w in ('工程', '单独完成', '合作效率', '工作量')):
                    chosen = code; break

            if not chosen and cand_matches:
                chosen = cand_matches[0]

            class_data = {
                'primary_knowledge_node_code': chosen,
                'secondary_knowledge_node_codes': [c for c in cand_matches if c != chosen][:1],
                'confidence': 0.93,
                'reason': f'题干特征与候选知识点 {chosen} 核心概念高度匹配。',
            }
            return json.dumps(class_data, ensure_ascii=False), {'prompt_tokens': 100, 'completion_tokens': 40, 'total_tokens': 140}

        elif 'primary_skill_code' in prompt_lower or 'skill classification' in prompt_lower:
            import re
            cand_matches = re.findall(r'"code":\s*"([^"]+)"', full_prompt)
            chosen_skill = cand_matches[0] if cand_matches else 'gongkao.learning.identify'
            skill_data = {
                'primary_skill_code': chosen_skill,
                'secondary_skill_codes': cand_matches[1:2] if len(cand_matches) > 1 else [],
                'supporting_skill_codes': [],
                'confidence': 0.91,
                'reason': f'该题核心认知技能要求为 {chosen_skill}。',
            }
            return json.dumps(skill_data, ensure_ascii=False), {'prompt_tokens': 90, 'completion_tokens': 35, 'total_tokens': 125}

        elif 'answer_matches_explanation' in prompt_lower or 'audit' in prompt_lower:
            audit_data = {
                'answer_matches_explanation': True,
                'explanation_supported_answer': 'B',
                'confidence': 0.95,
                'reason': '解析步骤推导与给定答案完全一致，无冲突。',
            }
            return json.dumps(audit_data, ensure_ascii=False), {'prompt_tokens': 70, 'completion_tokens': 30, 'total_tokens': 100}

        # Default fallback JSON or text
        if json_mode:
            fallback = {'status': 'success', 'model': config.model, 'summary': 'Mock generation complete.'}
            return json.dumps(fallback, ensure_ascii=False), {'prompt_tokens': 30, 'completion_tokens': 20, 'total_tokens': 50}

        return f'Mock response from {config.model} for policy.', {'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 30}
