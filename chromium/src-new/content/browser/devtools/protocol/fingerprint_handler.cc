// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "content/browser/devtools/protocol/fingerprint_handler.h"

#include "content/browser/renderer_host/render_frame_host_impl.h"
#include "content/browser/web_contents/web_contents_impl.h"
#include "content/public/browser/web_contents.h"

namespace content {
namespace protocol {

FingerprintHandler::FingerprintHandler()
    : DevToolsDomainHandler(Fingerprint::Metainfo::domainName) {}

FingerprintHandler::~FingerprintHandler() = default;

void FingerprintHandler::Wire(UberDispatcher* dispatcher) {
  Fingerprint::Dispatcher::wire(dispatcher, this);
}

void FingerprintHandler::SetRenderer(int process_host_id,
                                     RenderFrameHostImpl* frame_host) {
  host_ = frame_host;
}

WebContentsImpl* FingerprintHandler::GetWebContents() {
  if (!host_)
    return nullptr;
  return static_cast<WebContentsImpl*>(
      WebContents::FromRenderFrameHost(host_));
}

void FingerprintHandler::SetContextOverrides(
    const String& fingerprint,
    std::unique_ptr<SetContextOverridesCallback> callback) {
  if (auto* wc = GetWebContents()) {
    WebContentsImpl::SetBrowserContextFingerprint(wc->GetBrowserContext(),
                                                  fingerprint);
  }
  callback->sendSuccess();
}

}  // namespace protocol
}  // namespace content
