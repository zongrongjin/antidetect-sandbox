// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CONTENT_BROWSER_DEVTOOLS_PROTOCOL_FINGERPRINT_HANDLER_H_
#define CONTENT_BROWSER_DEVTOOLS_PROTOCOL_FINGERPRINT_HANDLER_H_

#include <memory>
#include <string>

#include "base/memory/raw_ptr.h"
#include "content/browser/devtools/protocol/devtools_domain_handler.h"
#include "content/browser/devtools/protocol/fingerprint.h"

namespace content {

class RenderFrameHostImpl;
class WebContentsImpl;

namespace protocol {

// //BROWSER_FINGERPRINT: 正式的 Fingerprint CDP 域——把指纹存到当前 target 的
// BrowserContext，该 context 的所有页面（含之后新建的 target）自动继承。
class FingerprintHandler : public DevToolsDomainHandler,
                           public Fingerprint::Backend {
 public:
  FingerprintHandler();

  FingerprintHandler(const FingerprintHandler&) = delete;
  FingerprintHandler& operator=(const FingerprintHandler&) = delete;

  ~FingerprintHandler() override;

  void Wire(UberDispatcher* dispatcher) override;
  void SetRenderer(int process_host_id,
                   RenderFrameHostImpl* frame_host) override;

  void SetContextOverrides(
      const String& fingerprint,
      std::unique_ptr<SetContextOverridesCallback> callback) override;

 private:
  WebContentsImpl* GetWebContents();

  raw_ptr<RenderFrameHostImpl> host_ = nullptr;
};

}  // namespace protocol
}  // namespace content

#endif  // CONTENT_BROWSER_DEVTOOLS_PROTOCOL_FINGERPRINT_HANDLER_H_
