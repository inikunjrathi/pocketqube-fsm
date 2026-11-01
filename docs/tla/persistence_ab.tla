---- MODULE persistence_ab ----
\* Hand-written model of the A/B bank protocol in engine/persistence.py and
\* mcu/firmware/app/src/engine_persistence.c (decision 0012). The per-config
\* modules abstract the banks as one durable snapshot; this one abstracts the
\* mission to a few contents and keeps both banks, each erase and program
\* step, resets at any point, torn records and single-bank corruption.
\*
\* Mutant selects a protocol change that must be rejected, so that the checks
\* below cannot silently become vacuous (tools/run_model_check.sh):
\*   "none"          the protocol as implemented
\*   "raw_target"    target chosen by raw sequence, ignoring validity
\*   "single_write"  a change writes one bank only
\*   "skip_either"   a save is skipped if either bank holds the content
EXTENDS Naturals, TLC

CONSTANTS Contents, Latched, MaxSeq, Mutant

Banks == {"A", "B"}
Other(b) == IF b = "A" THEN "B" ELSE "A"

VARIABLES
    bank,       \* per bank: [valid, seq, c]
    pc,         \* "idle", "program", "erase_other", "program_other"
    target,     \* the bank being written
    pending,    \* the content being saved
    committed,  \* content of the last save that returned, or "none"
    attempted,  \* contents tried since then, any of which may have landed
    clean       \* a save returned and nothing has faulted since

Vars == <<bank, pc, target, pending, committed, attempted, clean>>

Blank == [valid |-> FALSE, seq |-> 0, c |-> "none"]

Newest ==
    IF bank["A"].valid /\ bank["B"].valid
    THEN IF bank["A"].seq >= bank["B"].seq THEN "A" ELSE "B"
    ELSE IF bank["A"].valid THEN "A"
    ELSE IF bank["B"].valid THEN "B"
    ELSE "none"

Loaded == IF Newest = "none" THEN "none" ELSE bank[Newest].c

NextSeq == IF Newest = "none" THEN 0 ELSE bank[Newest].seq + 1

Holds(b, c) == bank[b].valid /\ bank[b].c = c

ChooseTarget ==
    IF Mutant = "raw_target"
    THEN IF bank["A"].seq >= bank["B"].seq THEN "B" ELSE "A"
    ELSE IF Newest = "A" THEN "B" ELSE "A"

Init ==
    /\ bank = [b \in Banks |-> Blank]
    /\ pc = "idle"
    /\ target = "A"
    /\ pending = "none"
    /\ committed = "none"
    /\ attempted = {}
    /\ clean = FALSE

\* A set latch is never cleared by the engine: contents may only move forward.
Allowed(c) ==
    /\ Loaded # "none" /\ Loaded \in Latched => c \in Latched
    /\ committed \in Latched => c \in Latched

Skip(c) ==
    IF Mutant = "skip_either"
    THEN Holds("A", c) \/ Holds("B", c)
    ELSE Holds("A", c) /\ Holds("B", c)

Commit(c) ==
    /\ pc' = "idle"
    /\ committed' = c
    /\ attempted' = {}
    /\ clean' = TRUE

Save(c) ==
    /\ pc = "idle"
    /\ Allowed(c)
    /\ IF Skip(c)
       THEN /\ Commit(c)
            /\ UNCHANGED <<bank, target, pending>>
       ELSE /\ target' = ChooseTarget
            /\ bank' = [bank EXCEPT ![ChooseTarget].valid = FALSE]  \* erase
            /\ pc' = "program"
            /\ pending' = c
            /\ attempted' = attempted \cup {c}
            /\ clean' = FALSE
            /\ UNCHANGED committed

Program ==
    /\ pc = "program"
    /\ bank' = [bank EXCEPT ![target] = [valid |-> TRUE, seq |-> NextSeq, c |-> pending]]
    /\ IF Holds(Other(target), pending) \/ Mutant = "single_write"
       THEN /\ Commit(pending)
       ELSE /\ pc' = "erase_other"
            /\ UNCHANGED <<committed, attempted, clean>>
    /\ UNCHANGED <<target, pending>>

EraseOther ==
    /\ pc = "erase_other"
    /\ bank' = [bank EXCEPT ![Other(target)].valid = FALSE]
    /\ pc' = "program_other"
    /\ UNCHANGED <<target, pending, committed, attempted, clean>>

ProgramOther ==
    /\ pc = "program_other"
    /\ bank' = [bank EXCEPT ![Other(target)] = [valid |-> TRUE, seq |-> NextSeq, c |-> pending]]
    /\ Commit(pending)
    /\ UNCHANGED <<target, pending>>

\* A reset at any point. A record torn during programming has its sequence
\* readable but no valid CRC.
Reset ==
    /\ pc # "idle"
    /\ \/ bank' = bank
       \/ /\ pc \in {"program", "program_other"}
          /\ LET b == IF pc = "program" THEN target ELSE Other(target)
             IN bank' = [bank EXCEPT ![b] = [valid |-> FALSE, seq |-> NextSeq, c |-> "none"]]
    /\ pc' = "idle"
    /\ UNCHANGED <<target, pending, committed, attempted, clean>>

\* A bit flip or retention failure, one bank at a time: the other bank must
\* be valid, so double faults stay out of scope. That includes corruption of
\* the new copy during a save, which a reset before the save ended would turn
\* into the loss of both banks.
Corrupt(b) ==
    /\ pc = "idle"
    /\ bank[b].valid
    /\ bank[Other(b)].valid
    /\ bank' = [bank EXCEPT ![b].valid = FALSE]
    /\ clean' = FALSE
    /\ UNCHANGED <<pc, target, pending, committed, attempted>>

Next ==
    \/ \E c \in Contents : Save(c)
    \/ Program \/ EraseOther \/ ProgramOther \/ Reset
    \/ \E b \in Banks : Corrupt(b)

Spec == Init /\ [][Next]_Vars

SeqBound == bank["A"].seq <= MaxSeq /\ bank["B"].seq <= MaxSeq

\* Once anything has committed, some bank can always be loaded.
AlwaysLoadable == committed # "none" => Loaded # "none"

\* A load returns the committed record or a newer attempt, never older.
NeverRollsBack == committed # "none" => Loaded \in attempted \cup {committed}

\* A committed latch is never lost.
LatchDurable == committed \in Latched => Loaded \in Latched

\* When a save returns with no fault since, either bank alone restores it.
BothBanksHold == clean => Holds("A", committed) /\ Holds("B", committed)

====
