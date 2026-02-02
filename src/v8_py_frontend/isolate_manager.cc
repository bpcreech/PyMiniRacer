#include "isolate_manager.h"
#include <libplatform/libplatform.h>
#include <v8-isolate.h>
#include <v8-local-handle.h>
#include <v8-locker.h>
#include <v8-microtask.h>
#include <v8-platform.h>
#include <thread>
#include <tuple>

namespace MiniRacer {

IsolateManager::IsolateManager(v8::Platform* platform)
    : platform_(platform),
      state_(State::kRun),
      allocator_(v8::ArrayBuffer::Allocator::NewDefaultAllocator()),
      isolate_([this]() -> v8::Isolate* {
        v8::Isolate::CreateParams create_params;
        create_params.array_buffer_allocator = allocator_.get();

        v8::Isolate* isolate = v8::Isolate::New(create_params);

        // We should set kExplicit since we're running the Microtasks checkpoint
        // manually in isolate_manager.cc. Per
        // https://stackoverflow.com/questions/54393127/v8-how-to-correctly-handle-microtasks
        isolate->SetMicrotasksPolicy(v8::MicrotasksPolicy::kExplicit);
        return isolate;
      }()),
      thread_([this]() { PumpMessages(); }) {}

IsolateManager::~IsolateManager() {
  ChangeState(State::kStop);
  thread_.join();
  isolate_->Dispose();
}

void IsolateManager::TerminateOngoingTask() {
  isolate_->TerminateExecution();
}

void IsolateManager::StopJavaScript() {
  ChangeState(State::kNoJavaScript);
  TerminateOngoingTask();
}

void IsolateManager::PumpMessages() {
  // By design, only this, the message pump thread, is ever allowed to touch
  // the isolate, so go ahead and lock it:
  const v8::Locker lock(isolate_);
  const v8::Isolate::Scope scope(isolate_);
  const v8::HandleScope handle_scope(isolate_);

  context_.Reset(isolate_, v8::Context::New(isolate_));

  const v8::SealHandleScope shs(isolate_);
  while (state_ == State::kRun) {
    v8::platform::PumpMessageLoop(
        platform_, isolate_, v8::platform::MessageLoopBehavior::kWaitForWork);

    if (state_ == State::kRun) {
      isolate_->PerformMicrotaskCheckpoint();
    }
  }

  const v8::Isolate::DisallowJavascriptExecutionScope disallow_js(
      isolate_, v8::Isolate::DisallowJavascriptExecutionScope::OnFailure::
                    THROW_ON_FAILURE);
  while (state_ == State::kNoJavaScript) {
    v8::platform::PumpMessageLoop(
        platform_, isolate_, v8::platform::MessageLoopBehavior::kWaitForWork);
  }

  context_.Reset();
}

void IsolateManager::ChangeState(State state) {
  state_ = state;
  // Run a no-op task to kick the message loop into noticing we've switched
  // states:
  std::ignore = Schedule([]() {});
}

}  // end namespace MiniRacer
