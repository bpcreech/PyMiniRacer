#ifndef INCLUDE_MINI_RACER_CALLBACK_H
#define INCLUDE_MINI_RACER_CALLBACK_H

#include <cstdint>
#include "value.h"

namespace MiniRacer {

using RawCallback = void (*)(uint64_t, ValueHandle*);

}  // end namespace MiniRacer

#endif  // INCLUDE_MINI_RACER_CALLBACK_H
