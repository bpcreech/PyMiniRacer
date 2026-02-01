#ifndef INCLUDE_MINI_RACER_ISOLATE_MANAGER_H
#define INCLUDE_MINI_RACER_ISOLATE_MANAGER_H

#include <v8-array-buffer.h>
#include <v8-context.h>
#include <v8-isolate.h>
#include <v8-local-handle.h>
#include <v8-persistent-handle.h>
#include <v8-platform.h>
#include <atomic>
#include <cstdint>
#include <future>
#include <memory>
#include <thread>
#include <type_traits>
#include <utility>

namespace MiniRacer {

class IsolateManager;

/** Wraps up a runnable to run on a v8::Isolate's foreground task runner thread
 * . */
template <typename Runnable>
class IsolateTask : public v8::Task {
 public:
  using ReturnType = std::invoke_result_t<Runnable>;
  using FutureType = std::future<ReturnType>;

  explicit IsolateTask(Runnable runnable, IsolateManager* isolate_manager);

  void Run() override;

  auto GetFuture() -> FutureType;

 private:
  std::packaged_task<ReturnType()> packaged_task_;
  IsolateManager* isolate_manager_;
};

/** Owns a v8::Isolate and mediates access to it via a task queue.
 *
 * Instances of v8::Isolate are not thread safe, and yet we need to run a
 * continuous message pump thread, and Python will call in from various
 * threads. One strategy for making an isolate thread-safe is to use a
 * v8::Locker to gate usage, but this seems hard to get right (especially
 * when the message pump thread blocks indefinitely on work and then dispatches
 * that work, apparently without bothering to grab the lock itself).
 * So instead we employ the strategy of "hiding" the isolate pointer within this
 * class, and only expose it via callbacks from the isolate's task queue.
 * Anything which wants to interact with the isolate must "get in line" by
 * scheduling a task with the IsolateManager. */
class IsolateManager {
 public:
  explicit IsolateManager(v8::Platform* platform);
  ~IsolateManager();

  IsolateManager(const IsolateManager&) = delete;
  auto operator=(const IsolateManager&) -> IsolateManager& = delete;
  IsolateManager(IsolateManager&&) = delete;
  auto operator=(IsolateManager&& other) -> IsolateManager& = delete;

  auto GetIsolate() -> v8::Isolate*;
  auto GetLocalContext() -> v8::Local<v8::Context>;

  /** Schedules a task to run on the foreground thread, using
   * v8::TaskRunner::PostTask. Returns a future which gets the result.
   * The caller should, of course, ensure that any references bound into the
   * runnable outlive the task, by awaiting the returned future before tearing
   * down any referred-to objects. */
  template <typename Runnable>
  [[nodiscard]] auto Schedule(Runnable runnable) ->
      typename IsolateTask<Runnable>::FutureType;

  void TerminateOngoingTask();

  void StopJavaScript();

 private:
  enum State : std::uint8_t {
    kRun = 0,
    kNoJavaScript = 1,
    kStop = 2,
  };

  void PumpMessages();
  void ChangeState(State state);

  v8::Platform* platform_;
  std::atomic<State> state_;
  std::unique_ptr<v8::ArrayBuffer::Allocator> allocator_;
  v8::Isolate* isolate_;
  std::thread thread_;
  v8::Global<v8::Context> context_;
};

inline auto IsolateManager::GetIsolate() -> v8::Isolate* {
  return isolate_;
}

inline auto IsolateManager::GetLocalContext() -> v8::Local<v8::Context> {
  return context_.Get(isolate_);
}

/** Schedules a task to run on the foreground thread, using
 * v8::TaskRunner::PostTask. Awaits task completion. */
template <typename Runnable>
inline auto IsolateManager::Schedule(Runnable runnable) ->
    typename IsolateTask<Runnable>::FutureType {
  auto task =
      std::make_unique<IsolateTask<Runnable>>(std::move(runnable), this);

  auto fut = task->GetFuture();

  platform_->GetForegroundTaskRunner(isolate_)->PostTask(std::move(task));

  return fut;
}

template <typename Runnable>
inline IsolateTask<Runnable>::IsolateTask(Runnable runnable,
                                          IsolateManager* isolate_manager)
    : packaged_task_(std::move(runnable)), isolate_manager_(isolate_manager) {}

template <typename Runnable>
inline void IsolateTask<Runnable>::Run() {
  v8::Isolate* isolate = isolate_manager_->GetIsolate();
  const v8::HandleScope handle_scope(isolate);
  const v8::Local<v8::Context> context = isolate_manager_->GetLocalContext();
  const v8::Context::Scope context_scope(context);

  packaged_task_();
}

template <typename Runnable>
inline auto IsolateTask<Runnable>::GetFuture()
    -> IsolateTask<Runnable>::FutureType {
  return packaged_task_.get_future();
}

}  // end namespace MiniRacer

#endif  // INCLUDE_MINI_RACER_ISOLATE_MANAGER_H
