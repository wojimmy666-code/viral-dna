from __future__ import annotations

import asyncio
import os
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from .models import (
    AnalysisJob,
    AnalysisReport,
    AnalysisStage,
    Entity,
    PromptPackage,
    PromptShot,
    ReplacementCreate,
    ReplacementDiff,
    ReplacementVersion,
    Shot,
    Video,
    VideoOverview,
    VideoStatus,
    ViralFinding,
)
from .store import InMemoryStore


def utc_now() -> datetime:
    return datetime.now(UTC)


class SimulatedAnalysisPipeline:
    """Deterministic vertical-slice analyzer used until real providers land.

    Every response is explicitly marked as simulated. The purpose is to stabilize
    the product flow, domain model and report contract before adding expensive AI calls.
    """

    stages = (
        (AnalysisStage.INGESTING, 8, "正在读取视频来源"),
        (AnalysisStage.PREPROCESSING, 20, "正在校验媒体并生成分析代理"),
        (AnalysisStage.SEGMENTING, 36, "正在识别镜头边界与关键帧"),
        (AnalysisStage.TRANSCRIBING, 50, "正在对齐语音与画面文字"),
        (AnalysisStage.UNDERSTANDING, 68, "正在提取人物、服装、场景与动作"),
        (AnalysisStage.REASONING, 82, "正在分析 Hook、节奏与传播机制"),
        (AnalysisStage.COMPILING_PROMPTS, 93, "正在编译逐镜头提示词"),
        (AnalysisStage.VALIDATING, 98, "正在检查时间线和提示词连续性"),
    )

    def __init__(self, repository: InMemoryStore) -> None:
        self.repository = repository
        self.delay_seconds = float(os.getenv("VIRAL_DNA_SIMULATION_DELAY", "0.28"))
        self._tasks: set[asyncio.Task[Any]] = set()

    def start(self, analysis_id: UUID) -> None:
        task = asyncio.create_task(self.run(analysis_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def run(self, analysis_id: UUID) -> None:
        analysis = await self.repository.get_analysis(analysis_id)
        if analysis is None:
            return

        video = await self.repository.get_video(analysis.video_id)
        if video is None:
            return

        try:
            video.status = VideoStatus.ANALYZING
            await self.repository.save_video(video)

            for stage, progress, message in self.stages:
                analysis.stage = stage
                analysis.progress = progress
                analysis.message = message
                analysis.updated_at = utc_now()
                await self.repository.save_analysis(analysis)
                await asyncio.sleep(self.delay_seconds)

            report = build_simulated_report(video, analysis)
            await self.repository.save_report(report)

            analysis.stage = AnalysisStage.COMPLETED
            analysis.progress = 100
            analysis.message = "分析完成，可查看报告"
            analysis.updated_at = utc_now()
            analysis.completed_at = utc_now()
            await self.repository.save_analysis(analysis)

            video.status = VideoStatus.COMPLETED
            video.duration_seconds = report.overview.duration_seconds
            video.width = 1080
            video.height = 1920
            video.fps = 30
            await self.repository.save_video(video)
        except Exception as exc:  # pragma: no cover - defensive orchestration boundary
            analysis.stage = AnalysisStage.FAILED
            analysis.progress = 100
            analysis.message = f"分析失败：{exc}"
            analysis.updated_at = utc_now()
            await self.repository.save_analysis(analysis)
            video.status = VideoStatus.FAILED
            await self.repository.save_video(video)


def build_simulated_report(video: Video, analysis: AnalysisJob) -> AnalysisReport:
    person = Entity(
        id="person_01",
        type="person",
        name="主讲人",
        description="约 28～35 岁的亚洲女性，黑色中长发，亲和自然，面对镜头表达",
        occurrence_shot_ids=["shot_01", "shot_02", "shot_03", "shot_05"],
        replaceable_fields=["年龄", "性别", "发型", "外貌", "气质"],
        confidence=0.88,
    )
    wardrobe = Entity(
        id="wardrobe_01",
        type="wardrobe",
        name="主讲人服装",
        description="暖白色针织上衣，低对比度，无明显图案",
        occurrence_shot_ids=["shot_01", "shot_02", "shot_03", "shot_05"],
        replaceable_fields=["颜色", "材质", "款式", "配饰"],
        confidence=0.91,
    )
    scene = Entity(
        id="scene_01",
        type="scene",
        name="家庭厨房",
        description="暖色现代家庭厨房，木质台面，柔和窗光，背景轻微虚化",
        occurrence_shot_ids=["shot_01", "shot_02", "shot_03", "shot_04", "shot_05"],
        replaceable_fields=["地点", "装修风格", "时间", "天气", "灯光"],
        confidence=0.94,
    )
    product = Entity(
        id="product_01",
        type="product",
        name="早餐成品",
        description="白色陶瓷盘中的健康早餐，具有清晰食材层次和热气",
        occurrence_shot_ids=["shot_01", "shot_03", "shot_04", "shot_05"],
        replaceable_fields=["品类", "颜色", "包装", "摆盘"],
        confidence=0.87,
    )

    shots = [
        Shot(
            id="shot_01",
            index=1,
            start_seconds=0,
            end_seconds=1.8,
            title="结果前置",
            subjects=["person_01", "product_01"],
            action="人物将成品早餐快速推向镜头，直视镜头并微笑",
            scene="scene_01",
            camera="中近景，略低机位，快速轻推镜",
            composition="人物居中，餐盘位于前景下三分之一",
            lighting="左侧柔和窗光，面部均匀补光",
            color="暖白、浅木色与少量绿色点缀",
            dialogue="每天早上只要三分钟。",
            ocr_text="3分钟搞定高蛋白早餐",
            audio="轻快节拍从第一帧进入，餐盘落桌声被强化",
            transition="首帧直接进入动作，无淡入",
            narrative_role="在两秒内交付结果承诺",
            prompt=(
                "9:16 竖屏写实短视频，中近景，暖色家庭厨房，一位亲和的亚洲女性把高蛋白早餐"
                "快速推向镜头，微笑直视观众，镜头轻微快速推进，柔和窗光，首帧即有动作，清晰食物细节。"
            ),
            confidence=0.91,
        ),
        Shot(
            id="shot_02",
            index=2,
            start_seconds=1.8,
            end_seconds=5.2,
            title="痛点对比",
            subjects=["person_01"],
            action="人物指向画面左侧的传统复杂早餐步骤，随后摇头",
            scene="scene_01",
            camera="固定中景，轻微手持感",
            composition="人物位于右侧三分之一，左侧为字幕空间",
            lighting="保持暖色主光，背景低对比",
            color="暖白和浅棕色",
            dialogue="别再六点起床准备一大桌了。",
            ocr_text="费时 / 难坚持 / 容易饿",
            audio="节拍延续，摇头时加入短促提示音",
            transition="硬切",
            narrative_role="指出旧方法成本，建立认知冲突",
            prompt="固定中景，人物站在画面右侧，指向左侧留白并摇头，表达传统早餐费时难坚持；暖色现代厨房，轻微自然手持，字幕空间清晰，动作简洁有节奏。",
            confidence=0.86,
        ),
        Shot(
            id="shot_03",
            index=3,
            start_seconds=5.2,
            end_seconds=11.6,
            title="三步过程",
            subjects=["person_01", "product_01"],
            action="三个连续动作：倒入食材、搅拌、放入加热设备",
            scene="scene_01",
            camera="俯拍特写与手部近景交替，节奏化硬切",
            composition="食材始终处于中心，手部从画面边缘进入",
            lighting="顶部柔光突出食物纹理",
            color="米白、浅黄和绿色食材形成干净对比",
            dialogue="倒进去、搅一下、加热两分钟。",
            ocr_text="1 倒入  2 搅拌  3 加热",
            audio="每一步匹配一次清脆点击音",
            transition="动作匹配剪辑",
            narrative_role="以低认知负担证明方法简单",
            prompt="连续三镜动作蒙太奇：俯拍倒入食材、手部近景快速搅拌、放入加热设备；食材居中，顶部柔光，干净暖白厨房，每一步以动作匹配硬切衔接，节奏紧凑。",
            confidence=0.89,
        ),
        Shot(
            id="shot_04",
            index=4,
            start_seconds=11.6,
            end_seconds=15.4,
            title="质感证明",
            subjects=["product_01"],
            action="勺子切开早餐成品，展示内部湿润质感和热气",
            scene="scene_01",
            camera="微距特写，缓慢横向移动",
            composition="产品充满画面，浅景深",
            lighting="逆侧光勾勒热气和边缘",
            color="暖金色高光，背景柔和奶油色",
            dialogue=None,
            ocr_text="高蛋白 · 低负担",
            audio="BGM 暂时降低，保留切开食物的细节音",
            transition="节奏由快转慢",
            narrative_role="用感官特写完成可信度和食欲回报",
            prompt="微距食物特写，勺子缓慢切开高蛋白早餐，内部湿润松软，清晰热气，逆侧光勾边，浅景深，镜头缓慢横移，暖金色高光，强调真实食物质感。",
            confidence=0.93,
        ),
        Shot(
            id="shot_05",
            index=5,
            start_seconds=15.4,
            end_seconds=20.8,
            title="收藏触发",
            subjects=["person_01", "product_01"],
            action="人物拿起餐盘，另一只手指向步骤清单，最后点头",
            scene="scene_01",
            camera="中近景，稳定机位，结尾轻微推进",
            composition="人物居中，步骤清单位于右侧",
            lighting="与首镜一致的柔和窗光",
            color="保持暖白和木色统一",
            dialogue="配方放在最后，先收藏明早直接做。",
            ocr_text="收藏这份三分钟配方",
            audio="主旋律回归，结尾落在完整节拍上",
            transition="定格 0.4 秒结束",
            narrative_role="给出明确收藏动作和使用时机",
            prompt="中近景回到同一位人物和同一厨房，人物端着早餐指向右侧步骤清单，直视镜头点头；稳定机位结尾轻推，暖色窗光与首镜完全一致，最后定格半秒。",
            confidence=0.9,
        ),
    ]

    findings = [
        ViralFinding(
            id="finding_hook",
            type="hook",
            title="结果先出现，降低理解成本",
            score=88,
            start_seconds=0,
            end_seconds=1.8,
            observation="第一帧即出现人物、完成品和明显推近动作，并给出三分钟承诺。",
            mechanism="结果前置同时满足视觉变化、时间收益和明确主题三个注意力条件。",
            expected_effect="提高前两秒停留意愿，让观众立即知道继续观看能得到什么。",
            recommendation="复刻时保留首帧动作和明确时间承诺，替换产品时不要改成铺垫开场。",
            confidence=0.9,
        ),
        ViralFinding(
            id="finding_structure",
            type="structure",
            title="痛点—步骤—质感回报结构清楚",
            score=84,
            start_seconds=1.8,
            end_seconds=15.4,
            observation="先否定复杂旧方法，再用三步动作证明简单，随后用微距完成感官回报。",
            mechanism="认知冲突后迅速给出可执行解法，快节奏过程与慢节奏结果形成节奏反差。",
            expected_effect="兼顾信息获取和观看满足感，减少中段流失。",
            recommendation="替换行业时仍保留旧方法成本、三步解法和结果特写三个节点。",
            confidence=0.86,
        ),
        ViralFinding(
            id="finding_save",
            type="interaction",
            title="给出明确收藏理由和使用时机",
            score=81,
            start_seconds=15.4,
            end_seconds=20.8,
            observation="结尾不是泛化地请求关注，而是提示观众明早直接使用配方。",
            mechanism="把收藏行为绑定到具体未来场景，比通用 CTA 更有工具价值。",
            expected_effect="提升收藏意愿，并强化内容的可执行属性。",
            recommendation="新提示词中保留具体时间或场景化 CTA，避免只写记得点赞。",
            confidence=0.83,
        ),
    ]

    prompt_package = PromptPackage(
        target_model=video.target_model,
        global_prompt=(
            "9:16 竖屏写实生活方式短视频，暖色现代家庭厨房，同一人物、服装和场景贯穿全片；"
            "自然窗光、低对比度、干净暖白与浅木色；剪辑从快速结果展示进入三步过程，"
            "再以微距质感特写减速，最后回到人物完成收藏引导。"
        ),
        continuity_locks=[
            "person_01 的面部、发型和体态跨镜头一致",
            "wardrobe_01 全片保持暖白色针织材质",
            "scene_01 的窗光方向、台面和背景布局一致",
            "产品摆盘在镜头 01、04、05 中保持一致",
        ],
        entities={
            person.id: person.description,
            wardrobe.id: wardrobe.description,
            scene.id: scene.description,
            product.id: product.description,
        },
        shots=[
            PromptShot(
                shot_id=shot.id,
                duration_seconds=round(shot.end_seconds - shot.start_seconds, 2),
                prompt=shot.prompt,
                negative_constraints=["不要改变主体身份", "不要增加无关人物", "不要生成乱码字幕"],
            )
            for shot in shots
        ],
        negative_constraints=[
            "避免人物面部跨镜头漂移",
            "避免手指畸形和餐具穿模",
            "避免厨房布局跳变",
            "避免自动添加品牌、水印或不可读文字",
            "避免镜头时长与指定时间线明显不符",
        ],
    )

    return AnalysisReport(
        video_id=video.id,
        analysis_id=analysis.id,
        overview=VideoOverview(
            summary="用结果前置和三步演示呈现一份省时早餐方案，并在结尾用具体使用场景触发收藏。",
            content_type="生活方式 / 美食教程",
            narrative_structure="结果承诺 → 旧方法痛点 → 三步过程 → 质感回报 → 收藏 CTA",
            audience_inference="时间紧张、关注健康饮食的 20～40 岁上班族；此项为内容推断。",
            visual_style="暖色、自然窗光、生活化写实、快速步骤与微距食物特写结合",
            duration_seconds=20.8,
            aspect_ratio="9:16",
            viral_potential_score=85,
            confidence=0.86,
        ),
        shots=shots,
        entities=[person, wardrobe, scene, product],
        viral_findings=findings,
        prompt_package=prompt_package,
    )


def create_replacement_version(
    video_id: UUID,
    report: AnalysisReport,
    request: ReplacementCreate,
) -> ReplacementVersion:
    package = report.prompt_package.model_copy(deep=True)
    package.id = uuid4()
    package.version += 1
    package.created_at = utc_now()

    entity_map = {entity.id: entity for entity in report.entities}
    diffs: list[ReplacementDiff] = []
    locked_text = "；保持" + "、".join(request.locks) + "不变"

    for replacement in request.replacements:
        entity = entity_map.get(replacement.entity_id)
        if entity is None:
            raise ValueError(f"未找到元素 {replacement.entity_id}")

        before = package.entities.get(entity.id, entity.description)
        package.entities[entity.id] = replacement.description
        affected = entity.occurrence_shot_ids

        for shot_prompt in package.shots:
            if shot_prompt.shot_id in affected:
                shot_prompt.prompt = (
                    f"{shot_prompt.prompt} 将 {entity.name} 替换为："
                    f"{replacement.description}{locked_text}。"
                )

        diffs.append(
            ReplacementDiff(
                entity_id=entity.id,
                before=before,
                after=replacement.description,
                affected_shot_ids=affected,
            )
        )

    package.continuity_locks.extend(f"替换后锁定：{lock}" for lock in request.locks)

    return ReplacementVersion(
        video_id=video_id,
        source_prompt_package_id=report.prompt_package.id,
        prompt_package=package,
        diffs=diffs,
        locks=list(request.locks),
    )


def track_task(task: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
    """Small helper retained for future non-pipeline background jobs."""
    return asyncio.create_task(task)
