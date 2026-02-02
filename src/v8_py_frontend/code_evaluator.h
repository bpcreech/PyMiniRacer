#ifndef INCLUDE_MINI_RACER_CODE_EVALUATOR_H
#define INCLUDE_MINI_RACER_CODE_EVALUATOR_H

#include "isolate_manager.h"
#include "isolate_memory_monitor.h"
#include "value.h"

namespace MiniRacer {

/** Parse and run arbitrary scripts within an isolate. */
class CodeEvaluator {
 public:
  CodeEvaluator(IsolateManager* isolate_manager,
                ValueFactory* val_factory,
                IsolateMemoryMonitor* memory_monitor);

  auto Eval(Value* code_ptr) -> Value::Ptr;

 private:
  IsolateManager* isolate_manager_;
  ValueFactory* val_factory_;
  IsolateMemoryMonitor* memory_monitor_;
};

}  // end namespace MiniRacer

#endif  // INCLUDE_MINI_RACER_CODE_EVALUATOR_H
