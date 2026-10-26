BEGIN IMMEDIATE;

-- 1. Shenlun materials and questions
CREATE TABLE shenlun_materials (
 id TEXT PRIMARY KEY,
 title TEXT NOT NULL,
 exam_year INTEGER NOT NULL,
 materials_json TEXT NOT NULL CHECK(json_valid(materials_json)),
 question_stem TEXT NOT NULL,
 reference_answer TEXT NOT NULL,
 max_words INTEGER NOT NULL DEFAULT 400,
 created_at TEXT NOT NULL
);

-- 2. Shenlun practice session tracking
CREATE TABLE shenlun_sessions (
 id TEXT PRIMARY KEY,
 material_id TEXT NOT NULL REFERENCES shenlun_materials(id) ON DELETE CASCADE,
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','completed')),
 started_at TEXT NOT NULL,
 completed_at TEXT,
 notes_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(notes_json)),
 first_draft TEXT,
 final_answer TEXT,
 revision_diff TEXT,
 created_at TEXT NOT NULL
);

-- 3. Structured assessments (5-dimensional rubric)
CREATE TABLE shenlun_assessments (
 id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES shenlun_sessions(id) ON DELETE CASCADE,
 assessment_stage TEXT NOT NULL CHECK(assessment_stage IN ('first_draft','final_answer')),
 coverage REAL NOT NULL CHECK(coverage BETWEEN 0 AND 1),
 abstraction REAL NOT NULL CHECK(abstraction BETWEEN 0 AND 1),
 precision REAL NOT NULL CHECK(precision BETWEEN 0 AND 1),
 structure REAL NOT NULL CHECK(structure BETWEEN 0 AND 1),
 conciseness REAL NOT NULL CHECK(conciseness BETWEEN 0 AND 1),
 overall_score REAL NOT NULL CHECK(overall_score BETWEEN 0 AND 100),
 missing_points_json TEXT NOT NULL CHECK(json_valid(missing_points_json)),
 redundant_points_json TEXT NOT NULL CHECK(json_valid(redundant_points_json)),
 weak_abstractions_json TEXT NOT NULL CHECK(json_valid(weak_abstractions_json)),
 wording_issues_json TEXT NOT NULL CHECK(json_valid(wording_issues_json)),
 next_action TEXT NOT NULL,
 created_at TEXT NOT NULL
);

-- 4. Shenlun Learner Model
CREATE TABLE shenlun_mastery_state (
 skill_key TEXT PRIMARY KEY,
 skill_name TEXT NOT NULL,
 score REAL NOT NULL CHECK(score BETWEEN 0 AND 1),
 evaluation_count INTEGER NOT NULL DEFAULT 0,
 updated_at TEXT NOT NULL
);

-- Seed baseline skills for Shenlun Learner Model
INSERT OR IGNORE INTO shenlun_mastery_state VALUES
 ('information_extraction', '材料信息提取', 0.5, 0, strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 ('information_synthesis', '同类要点合并', 0.5, 0, strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 ('abstraction', '宏观抽象提升', 0.5, 0, strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 ('language_conciseness', '语言精炼压缩', 0.5, 0, strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 ('structure_organization', '论述结构组织', 0.5, 0, strftime('%Y-%m-%dT%H:%M:%fZ','now'));

-- Seed a verified demo material
INSERT OR IGNORE INTO shenlun_materials VALUES (
 'shenlun-demo-01',
 '某省数字乡村建设与基层治理创新',
 2026,
 '[{"id":"m1","title":"材料 1：数字乡村的痛点与探索","content":"近年来，某县推进数字乡村建设，但初期遭遇不少瓶颈：部分乡村老人对智能手机和农技App不会用、不敢用；少数乡镇盲目上线政务应用，出现重建设轻维护的“僵尸软件”；村民反映办事虽有网络通道，但线下服务网点撤并后，老百姓找不到面对面的服务人员。"},' ||
  '{"id":"m2","title":"材料 2：多元协同破局机制","content":"针对上述难题，某县开展“数字赋能+服务下沉”专项行动：一是组织青年村干部和驻村队员设立“数字辅导小站”，手把手教老年人通过简版界面缴纳医保、挂号就医；二是整合政务平台，取缔功能重叠APP，推行“一网通办、指尖减负”；三是在村党群服务中心保留“人工代办专窗”，线上接单、线下跑腿，真正做到数字技术为人服务。"}]',
 '给定资料介绍了某县在推进数字乡村建设中遇到的问题及解决措施。请概括其主要问题，并归纳解决措施。（不超过 300 字）',
 '主要问题：\n1. 数字鸿沟明显，农村老年群体面临使用壁垒；\n2. 形式主义倾向，APP重复建设且缺乏后续运维；\n3. 线下服务缺位，网点撤并导致群众办事受阻。\n\n解决措施：\n1. 服务下沉赋能：设立辅导站开展数字教学，推广适老简版界面；\n2. 减负整合优化：清理冗余软件，推行统一平台与指尖减负；\n3. 线上线下融合：保留人工代办窗口，线上受理与线下代跑紧密结合。',
 300,
 strftime('%Y-%m-%dT%H:%M:%fZ','now')
);

INSERT INTO schema_migrations VALUES (8, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
