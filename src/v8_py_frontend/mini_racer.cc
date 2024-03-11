#include "mini_racer.h"
#include <libplatform/libplatform.h>
#include <v8-profiler.h>
#include "breaker_thread.h"

namespace MiniRacer {

namespace {
std::unique_ptr<v8::Platform> current_platform = nullptr;
}  // end anonymous namespace

void Context::BinaryValueFree(BinaryValue* v) {
  if (!v) {
    return;
  }
  switch (v->type) {
    case type_execute_exception:
    case type_parse_exception:
    case type_oom_exception:
    case type_timeout_exception:
    case type_terminated_exception:
    case type_str_utf8:
      delete[] v->bytes;
      break;
    case type_bool:
    case type_double:
    case type_date:
    case type_null:
    case type_integer:
    case type_function:  // no value implemented
    case type_symbol:
    case type_object:
    case type_invalid:
      // the other types are scalar values
      break;
    case type_shared_array_buffer:
    case type_array_buffer:
      backing_stores_.erase(v);
      break;
  }
  delete v;
}

void Context::StaticGCCallback(v8::Isolate* isolate,
                               v8::GCType type,
                               v8::GCCallbackFlags flags,
                               void* data) {
  static_cast<Context*>(data)->GCCallback(isolate);
}

void Context::GCCallback(v8::Isolate* isolate) {
  v8::HeapStatistics stats;
  isolate->GetHeapStatistics(&stats);
  size_t used = stats.used_heap_size();

  soft_memory_limit_reached_ =
      (soft_memory_limit_ > 0) && (used > soft_memory_limit_);
  isolate->MemoryPressureNotification((soft_memory_limit_reached_)
                                          ? v8::MemoryPressureLevel::kModerate
                                          : v8::MemoryPressureLevel::kNone);
  if ((hard_memory_limit_ > 0) && used > hard_memory_limit_) {
    hard_memory_limit_reached_ = true;
    isolate->TerminateExecution();
  }
}

void Context::SetHardMemoryLimit(size_t limit) {
  hard_memory_limit_ = limit;
  hard_memory_limit_reached_ = false;
}

void Context::SetSoftMemoryLimit(size_t limit) {
  soft_memory_limit_ = limit;
  soft_memory_limit_reached_ = false;
}

namespace {
bool maybe_fast_call(const std::string& code) {
  // Does the code string end with '()'?
  // TODO check if the string is an identifier
  return (code.size() > 2 && code[code.size() - 2] == '(' &&
          code[code.size() - 1] == ')');
}
}  // end anonymous namespace

BinaryValuePtr Context::SummarizeTryCatch(v8::Local<v8::Context>& context,
                                          const v8::TryCatch& trycatch,
                                          BinaryTypes resultType) {
  if (!trycatch.StackTrace(context).IsEmpty()) {
    v8::Local<v8::Value> stacktrace;

    if (trycatch.StackTrace(context).ToLocal(&stacktrace)) {
      std::optional<std::string> backtrace = ValueToUtf8String(stacktrace);
      if (backtrace.has_value()) {
        // Generally the backtrace from v8 starts with the exception message, so
        // we can skip the exception message (below) when we have the backtrace.
        return MakeBinaryValue(backtrace.value(), resultType);
      }
    }
  }

  // Fall back to the backtrace-less exception message:
  if (!trycatch.Exception()->IsNull()) {
    std::optional<std::string> message =
        ValueToUtf8String(trycatch.Exception());
    if (message.has_value()) {
      return MakeBinaryValue(message.value(), resultType);
    }
  }

  // Send no message at all; the recipient can fill in generic messages based on
  // the type code.
  return MakeBinaryValue("", resultType);
}

BinaryValuePtr Context::Eval(const std::string& code, unsigned long timeout) {
  v8::Locker lock(isolate_);
  v8::Isolate::Scope isolate_scope(isolate_);

  v8::TryCatch trycatch(isolate_);

  // Later in this function, we pump the v8 message loop.
  // Per comment in v8/samples/shell.cc, it is important not to pump the message
  // loop when there are v8::Local handles on the stack, as this may trigger a
  // stackless GC when the new conservative stack scanning flag is enabled. So
  // we don't use any v8::Local handles here; only in sub-scopes of this method.

  // Spawn a thread to inforce the timeout limit:
  BreakerThread breaker_thread(isolate_, timeout);

  bool parsed = false;
  bool executed = false;
  BinaryValuePtr ret;

  // Is it a single function call?
  if (maybe_fast_call(code)) {
    v8::HandleScope handle_scope(isolate_);
    v8::Local<v8::Context> context = context_->Get(isolate_);
    v8::Context::Scope context_scope(context);
    v8::Local<v8::String> identifier;
    v8::Local<v8::Value> func;

    // Let's check if the value is a callable identifier
    parsed = v8::String::NewFromUtf8(isolate_, code.data(),
                                     v8::NewStringType::kNormal,
                                     static_cast<int>(code.size() - 2))
                 .ToLocal(&identifier) &&
             context->Global()->Get(context, identifier).ToLocal(&func) &&
             func->IsFunction();

    if (parsed) {
      // Call the identifier
      v8::MaybeLocal<v8::Value> maybe_value =
          v8::Local<v8::Function>::Cast(func)->Call(
              context, v8::Undefined(isolate_), 0, {});
      if (!maybe_value.IsEmpty()) {
        executed = true;
        ret = ConvertV8ToBinary(context, maybe_value.ToLocalChecked());
      }
    }
  }

  // Fallback on a slower full Eval
  if (!executed) {
    v8::HandleScope handle_scope(isolate_);
    v8::Local<v8::Context> context = context_->Get(isolate_);
    v8::Context::Scope context_scope(context);
    v8::Local<v8::String> asString;
    v8::Local<v8::Script> script;

    parsed = v8::String::NewFromUtf8(isolate_, code.data(),
                                     v8::NewStringType::kNormal,
                                     static_cast<int>(code.size()))
                 .ToLocal(&asString) &&
             v8::Script::Compile(context, asString).ToLocal(&script) &&
             !script.IsEmpty();

    if (!parsed) {
      return SummarizeTryCatch(context, trycatch, type_parse_exception);
    }

    v8::MaybeLocal<v8::Value> maybe_value = script->Run(context);
    if (!maybe_value.IsEmpty()) {
      executed = true;
      ret = ConvertV8ToBinary(context, maybe_value.ToLocalChecked());
    }
  }

  if (executed) {
    // Execute all pending tasks

    while (!breaker_thread.timed_out() && !hard_memory_limit_reached_) {
      bool wait =
          isolate_->HasPendingBackgroundTasks();  // Only wait when needed
                                                  // otherwise it waits forever.

      // Run message loop items (like timers)
      if (!v8::platform::PumpMessageLoop(
              current_platform.get(), isolate_,
              (wait) ? v8::platform::MessageLoopBehavior::kWaitForWork
                     : v8::platform::MessageLoopBehavior::kDoNotWait)) {
        break;
      }
    }
  }

  breaker_thread.disengage();

  if (!executed) {
    // Still didn't execute. Find an error:
    v8::HandleScope handle_scope(isolate_);
    v8::Local<v8::Context> context = context_->Get(isolate_);
    v8::Context::Scope context_scope(context);

    BinaryTypes resultType;

    if (hard_memory_limit_reached_) {
      resultType = type_oom_exception;
    } else if (breaker_thread.timed_out()) {
      resultType = type_timeout_exception;
    } else if (trycatch.HasTerminated()) {
      resultType = type_terminated_exception;
    } else {
      resultType = type_execute_exception;
    }

    return SummarizeTryCatch(context, trycatch, resultType);
  }

  return ret;
}

std::optional<std::string> Context::ValueToUtf8String(
    v8::Local<v8::Value> value) {
  v8::String::Utf8Value utf8(isolate_, value);

  if (utf8.length()) {
    return std::make_optional(std::string(*utf8, utf8.length()));
  }

  return std::nullopt;
}

BinaryValuePtr Context::ConvertV8ToBinary(v8::Local<v8::Context> context,
                                          v8::Local<v8::Value> value) {
  v8::Isolate::Scope isolate_scope(isolate_);
  v8::HandleScope scope(isolate_);

  BinaryValuePtr res = MakeBinaryValue();

  if (value->IsNull() || value->IsUndefined()) {
    res->type = type_null;
  } else if (value->IsInt32()) {
    res->type = type_integer;
    auto val = value->Uint32Value(context).ToChecked();
    res->int_val = val;
  }
  // ECMA-262, 4.3.20
  // http://www.ecma-international.org/ecma-262/5.1/#sec-4.3.19
  else if (value->IsNumber()) {
    res->type = type_double;
    double val = value->NumberValue(context).ToChecked();
    res->double_val = val;
  } else if (value->IsBoolean()) {
    res->type = type_bool;
    res->int_val = (value->IsTrue() ? 1 : 0);
  } else if (value->IsFunction()) {
    res->type = type_function;
  } else if (value->IsSymbol()) {
    res->type = type_symbol;
  } else if (value->IsDate()) {
    res->type = type_date;
    v8::Local<v8::Date> date = v8::Local<v8::Date>::Cast(value);

    double timestamp = date->ValueOf();
    res->double_val = timestamp;
  } else if (value->IsString()) {
    v8::Local<v8::String> rstr = value->ToString(context).ToLocalChecked();

    res->type = type_str_utf8;
    res->len = size_t(rstr->Utf8Length(isolate_));  // in bytes
    size_t capacity = res->len + 1;
    res->bytes = new char[capacity];
    rstr->WriteUtf8(isolate_, res->bytes);
  } else if (value->IsSharedArrayBuffer() || value->IsArrayBuffer() ||
             value->IsArrayBufferView()) {
    std::shared_ptr<v8::BackingStore> backing_store;
    size_t offset = 0;
    size_t size = 0;

    if (value->IsArrayBufferView()) {
      v8::Local<v8::ArrayBufferView> view =
          v8::Local<v8::ArrayBufferView>::Cast(value);

      backing_store = view->Buffer()->GetBackingStore();
      offset = view->ByteOffset();
      size = view->ByteLength();
    } else if (value->IsSharedArrayBuffer()) {
      backing_store =
          v8::Local<v8::SharedArrayBuffer>::Cast(value)->GetBackingStore();
      size = backing_store->ByteLength();
    } else {
      backing_store =
          v8::Local<v8::ArrayBuffer>::Cast(value)->GetBackingStore();
      size = backing_store->ByteLength();
    }

    backing_stores_[res.get()] = backing_store;
    res->type = value->IsSharedArrayBuffer() ? type_shared_array_buffer
                                             : type_array_buffer;
    res->ptr_val = static_cast<char*>(backing_store->Data()) + offset;
    res->len = size;

  } else if (value->IsObject()) {
    res->type = type_object;
    res->int_val = value->ToObject(context).ToLocalChecked()->GetIdentityHash();
  } else {
    return BinaryValuePtr();
  }
  return res;
}

Context::~Context() {
  if (context_) {
    v8::Locker lock(isolate_);
    v8::Isolate::Scope isolate_scope(isolate_);

    backing_stores_.clear();
    context_->Reset();
    delete context_;
  }

  isolate_->Dispose();
}

void init_v8(char const* v8_flags,
             char const* icu_path,
             char const* snapshot_path) {
  v8::V8::InitializeICU(icu_path);
  v8::V8::InitializeExternalStartupDataFromFile(snapshot_path);

  if (v8_flags != nullptr) {
    v8::V8::SetFlagsFromString(v8_flags);
  }
  if (v8_flags != nullptr && strstr(v8_flags, "--single-threaded") != nullptr) {
    current_platform = v8::platform::NewSingleThreadedDefaultPlatform();
  } else {
    current_platform = v8::platform::NewDefaultPlatform();
  }
  v8::V8::InitializePlatform(current_platform.get());
  v8::V8::Initialize();
}

Context::Context()
    : allocator_(v8::ArrayBuffer::Allocator::NewDefaultAllocator()),
      soft_memory_limit_(0),
      soft_memory_limit_reached_(false),
      hard_memory_limit_(0),
      hard_memory_limit_reached_(false) {
  v8::Isolate::CreateParams create_params;
  create_params.array_buffer_allocator = allocator_.get();

  isolate_ = v8::Isolate::New(create_params);

  v8::Locker lock(isolate_);
  v8::Isolate::Scope isolate_scope(isolate_);
  v8::HandleScope handle_scope(isolate_);

  context_ =
      new v8::Persistent<v8::Context>(isolate_, v8::Context::New(isolate_));

  isolate_->AddGCEpilogueCallback(StaticGCCallback, this);
}

BinaryValuePtr Context::HeapStats() {
  v8::HeapStatistics stats;

  if (!isolate_) {
    return BinaryValuePtr();
  }

  v8::Locker lock(isolate_);
  v8::Isolate::Scope isolate_scope(isolate_);
  v8::HandleScope handle_scope(isolate_);

  v8::TryCatch trycatch(isolate_);
  v8::Local<v8::Context> context = context_->Get(isolate_);
  v8::Context::Scope context_scope(context);

  isolate_->GetHeapStatistics(&stats);

  v8::Local<v8::Object> stats_obj = v8::Object::New(isolate_);

  stats_obj
      ->Set(context,
            v8::String::NewFromUtf8Literal(isolate_, "total_physical_size"),
            v8::Number::New(isolate_, (double)stats.total_physical_size()))
      .Check();
  stats_obj
      ->Set(
          context,
          v8::String::NewFromUtf8Literal(isolate_,
                                         "total_heap_size_executable"),
          v8::Number::New(isolate_, (double)stats.total_heap_size_executable()))
      .Check();
  stats_obj
      ->Set(context,
            v8::String::NewFromUtf8Literal(isolate_, "total_heap_size"),
            v8::Number::New(isolate_, (double)stats.total_heap_size()))
      .Check();
  stats_obj
      ->Set(context, v8::String::NewFromUtf8Literal(isolate_, "used_heap_size"),
            v8::Number::New(isolate_, (double)stats.used_heap_size()))
      .Check();
  stats_obj
      ->Set(context,
            v8::String::NewFromUtf8Literal(isolate_, "heap_size_limit"),
            v8::Number::New(isolate_, (double)stats.heap_size_limit()))
      .Check();

  v8::Local<v8::String> output;
  if (!v8::JSON::Stringify(context, stats_obj).ToLocal(&output) ||
      output.IsEmpty()) {
    return BinaryValuePtr();
  }
  return ConvertV8ToBinary(context, output);
}

namespace {
// From v8/src/d8/d8-console.cc:
class StringOutputStream : public v8::OutputStream {
 public:
  WriteResult WriteAsciiChunk(char* data, int size) override {
    os_.write(data, size);
    return kContinue;
  }

  void EndOfStream() override {}

  std::string result() { return os_.str(); }

 private:
  std::ostringstream os_;
};
}  // end anonymous namespace

BinaryValuePtr Context::HeapSnapshot() {
  v8::Locker lock(isolate_);
  v8::Isolate::Scope isolate_scope(isolate_);
  v8::HandleScope handle_scope(isolate_);
  auto snap = isolate_->GetHeapProfiler()->TakeHeapSnapshot();
  StringOutputStream sos;
  snap->Serialize(&sos);
  return MakeBinaryValue(sos.result(), type_str_utf8);
}

}  // end namespace MiniRacer