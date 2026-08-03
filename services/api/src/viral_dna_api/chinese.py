from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)
CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")

# This fallback keeps the service usable before dependencies are installed. Production
# environments use OpenCC; Windows additionally has a native conversion fallback.
FALLBACK_TRANSLATION = str.maketrans(
    {
        "後": "后",
        "臺": "台",
        "裡": "里",
        "裏": "里",
        "為": "为",
        "與": "与",
        "個": "个",
        "這": "这",
        "時": "时",
        "間": "间",
        "畫": "画",
        "麵": "面",
        "場": "场",
        "景": "景",
        "鏡": "镜",
        "頭": "头",
        "視": "视",
        "頻": "频",
        "聲": "声",
        "對": "对",
        "話": "话",
        "說": "说",
        "聽": "听",
        "開": "开",
        "關": "关",
        "閉": "闭",
        "發": "发",
        "現": "现",
        "進": "进",
        "過": "过",
        "還": "还",
        "從": "从",
        "來": "来",
        "會": "会",
        "應": "应",
        "該": "该",
        "讓": "让",
        "無": "无",
        "實": "实",
        "體": "体",
        "風": "风",
        "格": "格",
        "燈": "灯",
        "光": "光",
        "顏": "颜",
        "色": "色",
        "節": "节",
        "奏": "奏",
        "轉": "转",
        "換": "换",
        "動": "动",
        "作": "作",
        "細": "细",
        "構": "构",
        "圖": "图",
        "標": "标",
        "題": "题",
        "內": "内",
        "容": "容",
        "資": "资",
        "訊": "讯",
        "數": "数",
        "據": "据",
        "導": "导",
        "匯": "汇",
        "檔": "档",
        "錄": "录",
        "製": "制",
        "複": "复",
        "觀": "观",
        "眾": "众",
        "點": "点",
        "擊": "击",
        "贊": "赞",
        "傳": "传",
        "統": "统",
        "簡": "简",
        "單": "单",
        "優": "优",
        "勢": "势",
        "總": "总",
        "結": "结",
        "報": "报",
        "告": "告",
        "讀": "读",
        "寫": "写",
        "區": "区",
        "級": "级",
        "徑": "径",
        "選": "选",
        "擇": "择",
        "儲": "储",
        "存": "存",
        "檢": "检",
        "測": "测",
        "驗": "验",
        "證": "证",
        "權": "权",
        "限": "限",
        "錯": "错",
        "誤": "误",
        "務": "务",
        "態": "态",
        "價": "价",
        "錢": "钱",
        "費": "费",
        "雲": "云",
        "網": "网",
        "鏈": "链",
        "接": "接",
    }
)


@lru_cache(maxsize=1)
def _opencc_converter():
    try:
        from opencc import OpenCC
    except ImportError:
        return None
    return OpenCC("t2s")


def _windows_convert(text: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        flag_simplified_chinese = 0x02000000
        required = kernel32.LCMapStringEx(
            "zh-CN",
            flag_simplified_chinese,
            text,
            len(text),
            None,
            0,
            None,
            None,
            0,
        )
        if required <= 0:
            return None
        output = ctypes.create_unicode_buffer(required)
        written = kernel32.LCMapStringEx(
            "zh-CN",
            flag_simplified_chinese,
            text,
            len(text),
            output,
            required,
            None,
            None,
            0,
        )
        return output.value if written > 0 else None
    except (AttributeError, OSError, ValueError):
        return None


def to_simplified(text: str | None) -> str | None:
    if text is None or not CJK_PATTERN.search(text):
        return text
    converter = _opencc_converter()
    if converter is not None:
        return str(converter.convert(text)).translate(FALLBACK_TRANSLATION)
    native = _windows_convert(text)
    if native is not None:
        return native.translate(FALLBACK_TRANSLATION)
    return text.translate(FALLBACK_TRANSLATION)


def simplify_value(value: Any) -> Any:
    if isinstance(value, str):
        return to_simplified(value)
    if isinstance(value, list):
        return [simplify_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(simplify_value(item) for item in value)
    if isinstance(value, dict):
        return {key: simplify_value(item) for key, item in value.items()}
    return value


def simplify_model(model: ModelT) -> ModelT:
    payload = simplify_value(model.model_dump(mode="python"))
    return type(model).model_validate(payload)
