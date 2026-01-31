#ifndef INCLUDE_MINI_RACER_CALLBACK_H
#define INCLUDE_MINI_RACER_CALLBACK_H

#include <cstdint>
#include <functional>
#include "value.h"

namespace MiniRacer {

using RawCallback = void (*)(uint64_t, ValueHandle*);

using CallbackFn = std::function<void(uint64_t, Value::Ptr)>;

}  // end namespace MiniRacer

#endif  // INCLUDE_MINI_RACER_CALLBACK_H
