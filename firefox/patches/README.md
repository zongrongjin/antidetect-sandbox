# firefox/patches

只打 `fp_all.diff`。官方 tarball `firefox-152.0.5.source.tar.xz` 解压后的目录。

不要再跑开源仓库的 `patch_context_module.py`、`patch_android_surface.py`、`patch_input_trusted.py`、`patch_offscreen_webgl.py`，也不要叠开源仓库的 `fp_all.diff` 或那几份阶段 diff。

`bidi-module/` 里的 `.sys.mjs` 与 `fp_all.diff` 新增的模块是同一份内容，给阅读用。`fp_apply.sh` 不拷这个目录。
