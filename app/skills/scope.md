# Scope policy

Explicit filters execute directly. Inputs with at most 20 candidate words execute directly. For more than 100 candidates without explicit filters, the application sends `scope_confirm`. Ambiguous pools from 50 through 100 candidates, or more than 60 percent existing words, may request scope. After two clarification rounds use top 30, include existing words, and return the applied filter. Difficulty filters require verified labels; unknown labels are never guessed.
