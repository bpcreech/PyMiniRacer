#include "cancelable_task_runner.h"

#include <memory>
#include <mutex>
#include <utility>
#include "task_runner.h"

namespace MiniRacer {

CancelableTaskState::CancelableTaskState(TaskRunner* task_runner)
    : task_runner_(task_runner), state_(State::kNotStarted) {}

void CancelableTaskState::Cancel() {
  const std::lock_guard<std::mutex> lock(mutex_);

  if (state_ == State::kCanceled || state_ == State::kCompleted) {
    return;
  }

  if (state_ == State::kRunning) {
    task_runner_->TerminateOngoingTask();
  }

  state_ = State::kCanceled;
}

auto CancelableTaskState::SetRunningIfNotCanceled() -> bool {
  const std::lock_guard<std::mutex> lock(mutex_);
  if (state_ == State::kCanceled) {
    return false;
  }

  state_ = State::kRunning;
  return true;
}

auto CancelableTaskState::SetCompleteIfNotCanceled() -> bool {
  const std::lock_guard<std::mutex> lock(mutex_);
  if (state_ == State::kCanceled) {
    return false;
  }

  state_ = State::kCompleted;
  return true;
}

CancelableTaskHandle::CancelableTaskHandle(
    std::shared_ptr<CancelableTaskState> task_state)
    : task_state_(std::move(task_state)) {}

CancelableTaskHandle::~CancelableTaskHandle() {
  // Cancel if the task hasn't completed yet. (No-op if it has.)
  Cancel();
}

void CancelableTaskHandle::Cancel() {
  task_state_->Cancel();
}

CancelableTaskRunner::CancelableTaskRunner(TaskRunner* task_runner)
    : task_runner_(task_runner) {}

}  // end namespace MiniRacer