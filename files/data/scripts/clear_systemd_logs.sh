#!/usr/bin/env bash
journalctl --rotate
journalctl --vacuum-time=1s