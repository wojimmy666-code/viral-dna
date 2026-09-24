# 无原视频关键帧的参考图创作

## 输入契约

- 纯文字：`text_to_image`，不带底图和参考图；普通项目绑定资产后改用参考图创作，不静默忽略资产。
- 参考图创作：`reference_to_image`，无需原视频。人物、服装、商品、场景、风格等引用按角色排序，图片编号从 1 开始。
- 底图编辑：`keyframe_edit`，底图是图片 1，参考从图片 2 开始。`base_image_candidate_id` 为空表示原视频关键帧；非空必须属于当前项目、分镜、画面，并且未归档、文件可读、哈希一致。
- 生成参数中明确选择底图；候选预览和人工采用不能隐式改变底图。当前服务通过 `supports_candidate_base_image` 声明能力，旧服务未更新时阻止候选底图提交。
- 保留模型输入能力、实际图片总数、人物身份唯一性、素材权利、文件存在和哈希检查。模型不兼容时提示用户，不切换模型或丢弃资产。
- 新生成结果保留为新候选；不覆盖底图、原始关键帧、历史和人工采用。Skill 旧请求的文字模式加参考图仍兼容。

## 自动验收

1. `npm run test:web`：实际提交函数验证无底图人物／商品参考、纯文字、明确候选底图、原关键帧，以及保存失败和旧服务阻止提交。
2. `npm --workspace apps/web run test:image-input-browser`：真实工作台组件、独立临时浏览器，1440／390 宽度；参考生成可点击、显式底图选择、失效底图阻止、切换模式不调用生成、无横向溢出。
3. `npm run check:design`、`npm run build:web`。
4. `.venv\Scripts\python.exe -m pytest services/api/tests/test_image_input_modes.py services/api/tests/test_image_generation.py services/api/tests/test_generation_jobs.py services/api/tests/test_local_skill_images.py services/api/tests/test_image_batches.py`。

后端测试使用临时目录和模拟工具，检查实际输入文件、角色、输入快照及生成结果；覆盖越项目／分镜／画面、归档、丢失和被改动的底图。不调用付费模型，不修改真实项目。

## 人工验收

更新后重启 API 并刷新页面。打开无原视频关键帧的分镜，通过现有资产／`@` 入口选择人物或其他素材，填写修改要求，参数应显示“参考图创作”，不再出现要求选择原视频关键帧的错误。若需保留某张生成图的构图，打开参数，选择“底图编辑”及具体底图后再生成；核对新候选和原候选均保留。
