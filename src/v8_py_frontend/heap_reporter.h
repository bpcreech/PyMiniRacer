#ifndef INCLUDE_MINI_RACER_HEAP_REPORTER_H
#define INCLUDE_MINI_RACER_HEAP_REPORTER_H

#include "isolate_manager.h"
#include "value.h"

namespace MiniRacer {

/** Report fun facts about an isolate heap */
class HeapReporter {
 public:
  HeapReporter(IsolateManager* isolate_manager, ValueFactory* val_factory);

  auto HeapSnapshot() -> Value::Ptr;
  auto HeapStats() -> Value::Ptr;

 private:
  IsolateManager* isolate_manager_;
  ValueFactory* val_factory_;
};

}  // end namespace MiniRacer

#endif  // INCLUDE_MINI_RACER_HEAP_REPORTER_H
