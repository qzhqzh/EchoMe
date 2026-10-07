"""Register the real Blender probe through MCP and replay it in another process.

Use only with an explicitly selected development Hub. Credentials are read from
a local file and are never printed. No role/appearance acceptance is fabricated.
"""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime, timezone
from pathlib import Path

import httpx

from echome_mcp.tools.knowledge import echome_knowledge_read, echome_knowledge_write


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hub-url", required=True)
    parser.add_argument("--login-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--blender", required=True)
    args = parser.parse_args()
    if args.hub_url.rstrip("/") != "http://127.0.0.1:20110":
        raise SystemExit(
            "This acceptance harness is restricted to the isolated local Hub on port 20110"
        )
    output = args.output_dir.resolve()
    manifest_path = output / "knowledge-records.json"
    ids = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    report = json.loads((output / "checks.json").read_text())
    assert report["saved_file_reopened"] and len(report["previews"]) == 3
    login = json.loads(args.login_file.read_text())
    os.environ["ECHOME_KNOWLEDGE_HUB_URL"] = args.hub_url
    async with httpx.AsyncClient(
        base_url=args.hub_url, headers={"Authorization": "Bearer " + login["token"]}
    ) as owner:
        credential_path = output / "agent-token.json"
        if not credential_path.exists():
            response = await owner.post(
                "/api/v1/knowledge/agent-tokens", json={"name": "Blender acceptance agent"}
            )
            response.raise_for_status()
            credential_path.write_text(json.dumps(response.json()))
            credential_path.chmod(0o600)
        os.environ["ECHOME_KNOWLEDGE_TOKEN"] = json.loads(credential_path.read_text())["token"]

    async def save(key: str, kind: str, data: dict) -> dict:
        if key in ids:
            return json.loads(await echome_knowledge_read("get", ids[key]))
        result = json.loads(
            await echome_knowledge_write(
                "create", {"kind": kind, "data": data, "reason": "真实 Blender 技术链路验收"}
            )
        )
        if "error" in result:
            raise RuntimeError(result["error"])
        ids[key] = result["id"]
        manifest_path.write_text(json.dumps(ids, ensure_ascii=False, indent=2))
        return result

    async def asset(key: str, path: Path, media_type: str) -> str:
        if key in ids:
            return ids[key]
        async with httpx.AsyncClient(
            base_url=args.hub_url,
            headers={"Authorization": "Bearer " + os.environ["ECHOME_KNOWLEDGE_TOKEN"]},
            timeout=60,
        ) as client:
            response = await client.post(
                "/api/v1/knowledge/assets",
                params={"filename": path.name},
                content=path.read_bytes(),
                headers={"Content-Type": media_type},
            )
            response.raise_for_status()
            ids[key] = response.json()["resource_ref"]
            manifest_path.write_text(json.dumps(ids, ensure_ascii=False, indent=2))
            return ids[key]

    project = await save(
        "project",
        "project",
        {
            "name": "AI 构建 3D 鲸鱼娘",
            "status": "active",
            "summary": "用真实 Blender 执行验证知识积累、成果追溯和跨会话复用。当前为技术体块实验，角色外观待参考素材。",
        },
    )
    criteria = await save(
        "project_page",
        "page",
        {
            "title": "鲸鱼娘：目标与交付标准",
            "bindings": [{"target_id": project["id"], "role": "overview"}],
            "body_md": "# AI 构建 3D 鲸鱼娘\n\n## 当前阶段\n已执行独立 Blender 技术链路实验；**样件不是最终角色交付**。用户的参考图、角色比例、材质和用途仍待补充。\n\n## 工作方式\n现有 AI / Blender 环境负责执行；EchoMe 保存问题、知识、过程和实际输出。\n\n## 技术链路检查\n- `.blend` 文件确实存在并可重新打开。\n- 三个视角预览可查看。\n- 提供实际脚本和执行环境。\n- 新会话能找回所用知识版本、资料和成果。\n\n## 角色交付验收（尚未完成）\n- 依据用户参考图检查角色外形与比例。\n- 用户确认用途、材质精度及是否需要绑定或动画。\n- 对具体成果版本做验收；文件生成成功不代表外观通过。",
        },
    )
    question = await save(
        "question",
        "question",
        {
            "title": "AI 如何构建 Blender 建模？",
            "project_id": project["id"],
            "status": "investigating",
        },
    )
    domain = await save(
        "domain",
        "entity",
        {
            "name": "数字创作",
            "entity_kind": "topic",
            "summary": "使用数字工具创作可编辑的视觉内容，逐步积累方法与案例。",
        },
    )
    domain_position = await save("domain_position", "placement", {"entity_id": domain["id"]})
    subdomain = await save(
        "subdomain",
        "entity",
        {
            "name": "3D 建模与交付",
            "entity_kind": "topic",
            "summary": "关注模型的构建、观察、文件交付与复现。",
        },
    )
    sub_position = await save(
        "subdomain_position",
        "placement",
        {"entity_id": subdomain["id"], "parent_id": domain_position["id"]},
    )
    knowledge = await save(
        "knowledge",
        "entity",
        {
            "name": "Blender 程序化建模与多视角检查",
            "entity_kind": "method",
            "summary": "用脚本建立可编辑的模型，并通过保存、重开和多视角渲染检查实际输出。适用效果取决于对象与需求。",
            "personal_note": "已跑通当前体块实验的文件与预览链路；尚未验证复杂角色造型、拓扑、绑定和动画。",
        },
    )
    await save(
        "knowledge_position",
        "placement",
        {"entity_id": knowledge["id"], "parent_id": sub_position["id"]},
    )
    knowledge_page = await save(
        "knowledge_page",
        "page",
        {
            "title": "Blender 程序化建模：方法与限制",
            "bindings": [{"target_id": knowledge["id"], "role": "overview"}],
            "body_md": "## 方法\n1. 先写明输入、目标和检查标准。\n2. 用脚本创建几何、材质、灯光和相机。\n3. 保存可编辑 `.blend`。\n4. 观察多个视角，再在另一个进程中重新打开文件。\n5. 保存实际脚本、版本、预览和未解决问题。\n\n## 本次经验的范围\n在本机 Blender 5.2.0 LTS 的简单鲸鱼体块实验中运行成功。它说明此技术链路可执行，**不能证明复杂角色造型一定达标**。\n\n## 使用时注意\n- 先明确角色参考，再谈外形验收。\n- 不根据单个视角判断完整三维比例。\n- 文件生成、方法有用、人工核对与成果验收分别记录。",
        },
    )
    command = f"{args.blender} --background --factory-startup --threads 4 --python scripts/knowledge_blender_probe.py -- /tmp/echome-blender-reproduction"
    reproduction = await save(
        "reproduction_page",
        "page",
        {
            "title": "Blender 技术实验：执行与实际检查",
            "bindings": [{"target_id": question["id"], "role": "overview"}],
            "body_md": "## 实验输入\n本仓库 `scripts/knowledge_blender_probe.py`；生成简单鲸鱼体块以验证技术链路，不使用未提供的角色参考图。\n\n## 实际环境\nBlender "
            + report["blender_version"]
            + "\n\n## 复现命令\n```bash\n"
            + command
            + "\n```\n\n## 已执行的检查\n```json\n"
            + json.dumps(report, ensure_ascii=False, indent=2)
            + "\n```\n\n## 结论边界\n源文件已重新打开，三幅预览已产生。复杂角色外观与生产拓扑仍未验收。",
        },
    )
    source = await save(
        "source",
        "source",
        {
            "title": "本机 Blender 技术实验的执行记录",
            "source_kind": "practice",
            "context_ids": [question["id"], knowledge["id"]],
            "origin_ref": "scripts/knowledge_blender_probe.py + checks.json",
            "retention": "internal_version",
            "page_id": reproduction["id"],
            "page_revision": 1,
        },
    )
    predicate = await save(
        "predicate",
        "predicate",
        {
            "code": "observed_result",
            "label": "本次观察到",
            "value_kind": "scalar",
            "description": "在明确条件下观察到的实践结果，不推导为普遍保证。",
        },
    )
    relation = await save(
        "relation",
        "relation",
        {
            "subject_id": knowledge["id"],
            "predicate_id": predicate["id"],
            "object_value": {
                "type": "string",
                "value": "生成可编辑 .blend，重新打开成功，并产出三视角预览",
            },
            "statement_md": "本次简单鲸鱼体块脚本成功完成保存、重开与多角度渲染。",
            "perspective": "personal",
            "qualifiers": {
                "blender": report["blender_version"],
                "model_scope": "simple volume probe",
                "character_acceptance": "pending",
            },
            "evidence": [
                {
                    "source_id": source["id"],
                    "source_revision": 1,
                    "locator": "已执行的检查 / 结论边界",
                    "quote": "源文件已重新打开，三幅预览已产生。",
                    "role": "supports",
                }
            ],
        },
    )
    blend_ref = await asset(
        "blend_asset", output / "whale-volume-probe.blend", "application/octet-stream"
    )
    previews = [
        await asset(name + "_asset", output / (name + ".png"), "image/png")
        for name in ("front", "side", "back")
    ]
    deliverable = await save(
        "deliverable",
        "deliverable",
        {
            "title": "Blender 技术体块样件（非最终角色）",
            "project_id": project["id"],
            "question_id": question["id"],
            "resource_ref": blend_ref,
            "preview_refs": previews,
            "format": "blend",
            "reproduction_page_id": reproduction["id"],
            "reproduction_page_revision": 1,
        },
    )
    script_ref = await asset(
        "script_asset", Path(__file__).with_name("knowledge_blender_probe.py"), "text/plain"
    )
    await save(
        "script_deliverable",
        "deliverable",
        {
            "title": "技术样件的实际生成脚本",
            "question_id": question["id"],
            "resource_ref": script_ref,
            "format": "py",
        },
    )
    await save(
        "usage",
        "usage",
        {
            "context_id": question["id"],
            "knowledge_id": knowledge["id"],
            "knowledge_revision": 1,
            "page_id": knowledge_page["id"],
            "page_revision": 1,
            "deliverable_id": deliverable["id"],
            "deliverable_revision": 1,
            "role": "used",
            "application_note": "用简单鲸鱼体块验证可编辑源文件、三视角预览和重开链路；未对鲸鱼娘外观做通过判断。",
        },
    )
    await save(
        "relation_usage",
        "usage",
        {
            "context_id": question["id"],
            "knowledge_id": relation["id"],
            "knowledge_revision": 1,
            "role": "derived",
            "application_note": "只提炼本次实际观察到的结果，并保留实验范围。",
        },
    )
    await save(
        "acceptance",
        "acceptance",
        {
            "deliverable_id": deliverable["id"],
            "deliverable_revision": 1,
            "criteria_page_id": criteria["id"],
            "criteria_page_revision": 1,
            "state": "submitted",
            "checks": json.dumps(report, ensure_ascii=False),
            "note": "自动检查通过；角色外观待用户参考与人工验收，不标为 accepted。",
        },
    )
    await save(
        "review",
        "review",
        {
            "title": "核对本次 Blender 结论的适用范围",
            "issue_kind": "verification",
            "explanation": "实际执行记录支持简单体块的文件链路。请检查这条知识是否准确保留了限制，避免后续 AI 推广为复杂角色的质量保证。",
            "targets": [{"id": relation["id"], "revision": 1}],
            "proposal": {"operation": "verify", "target_id": relation["id"]},
        },
    )

    # Start a separate interpreter: the next session retrieves exactly the stored knowledge ID.
    replay_code = """import asyncio,json,sys
from echome_mcp.tools.knowledge import echome_knowledge_read
async def main():
 result=json.loads(await echome_knowledge_read('context',sys.argv[1]))
 assert any(r['id']==sys.argv[2] for r in result['records'])
 assert any(r['kind']=='source' for r in result['pinned_versions'])
 print(json.dumps({'retrieved':True,'records':len(result['records']),'pinned_versions':len(result['pinned_versions']),'truncated':result['truncated']}))
asyncio.run(main())"""
    replay = subprocess.run(
        [os.sys.executable, "-c", replay_code, project["id"], knowledge["id"]],
        check=True,
        capture_output=True,
        text=True,
    )
    retrieved = json.loads(replay.stdout)
    reopened = subprocess.run(
        [
            args.blender,
            "--background",
            "--disable-autoexec",
            str(output / "whale-volume-probe.blend"),
            "--python-expr",
            "import bpy,json; print('ECHOME_REOPEN '+json.dumps({'meshes':len([o for o in bpy.data.objects if o.type=='MESH']),'version':bpy.app.version_string}))",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    replay_line = next(
        line for line in reopened.stdout.splitlines() if line.startswith("ECHOME_REOPEN ")
    )
    reopened_report = json.loads(replay_line.split(" ", 1)[1])
    assert reopened_report["meshes"] == report["mesh_objects"]
    q2 = await save(
        "reuse_question",
        "question",
        {
            "title": "新会话如何找回建模方法并继续打开模型？",
            "status": "resolved",
            "resolution_note": "已在独立 Python 进程通过 MCP 找回知识与固定版本，并在另一个 Blender 进程重开实际 .blend，网格数量一致。",
        },
    )
    await save(
        "reuse_usage",
        "usage",
        {
            "context_id": q2["id"],
            "knowledge_id": knowledge["id"],
            "knowledge_revision": 1,
            "page_id": knowledge_page["id"],
            "page_revision": 1,
            "role": "used",
            "application_note": json.dumps(
                {"context_replay": retrieved, "blender_reopen": reopened_report}, ensure_ascii=False
            ),
        },
    )
    summary = {
        "project_id": project["id"],
        "question_id": question["id"],
        "knowledge_id": knowledge["id"],
        "reuse_question_id": q2["id"],
        "deliverable_id": deliverable["id"],
        "context_replay": retrieved,
        "blender_reopen": reopened_report,
        "blend_sha256": hashlib.sha256(
            (output / "whale-volume-probe.blend").read_bytes()
        ).hexdigest(),
        "checked_at": datetime.now(UTC).isoformat(),
        "character_appearance": "pending_user_reference",
    }
    (output / "acceptance-report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
