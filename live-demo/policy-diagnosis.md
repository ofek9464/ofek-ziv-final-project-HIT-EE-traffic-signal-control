# Investigation of constant actions

## Verified observations

The Heavy west multi-seed weights were loaded directly into QNetwork and ActorCritic, independently of the browser, TraCI instrumentation and safety overrides. The diagnostic used 4,096 synthetic normalized vectors with a binary phase and phase elapsed of 1/60. These vectors probe the networks and are outside the measured live-state distribution.

DQN selected 20 seconds for all synthetic vectors. A2C selected 30 seconds for all synthetic vectors. Output values changed across inputs while the highest-ranked action remained the same. See policy-diagnosis.json for score ranges and exact weight paths.

A real 1,200-second SUMO rollout on Heavy west seed 201 also selected 20 seconds for all 84 DQN decisions and 30 seconds for all 62 A2C decisions. This covered both junctions and 27 and 23 distinct queue configurations respectively. See presentation-action-distribution.json.

The UI is displaying the greedy policies learned by these checkpoints. Randomizing actions would change the evaluated controller. The presentation now exposes actual score values and the observed action counts for the selected junction.

## Training factors supported by source inspection

Both training scripts sum unscaled negative network-wide waiting and stop costs between decisions. Decision duration affects the number of terms accumulated. They use one fixed discount per decision despite variable elapsed time. This introduces duration-dependent reward and discount scales and is a plausible contributor to the DQN preference for short greens. It has not been isolated by an ablation experiment.

Checkpoint selection uses the single best training episode across randomized demand seeds. DQN training includes exploratory actions, so that episode reward is not an evaluation of the saved greedy policy. The DQN best logged episode is 702 with epsilon 0.1213.

A2C computes unnormalized returns and advantages and combines them with a squared critic loss and an entropy coefficient of 0.01. Its best logged episode is 125 with a total loss of 11,894,559,744. This scale is consistent with a critic-dominated objective and an action-concentrated actor. Establishing its causal contribution requires retraining and held-out evaluation.

A2C saves the network after updating it using the reward collected before that update. The checkpoint reward therefore measures the pre-update policy.

## Scope of the repair

The demo retains the project checkpoints and their original greedy action selection. It shows measured policy behavior, including repeated choices, and preserves the distinction between the network recommendation and applied safety-constrained duration. Its comparison metric remains completed-trip waiting time for each independent SUMO run under the same demand seed.

This investigation establishes where the constant choice occurs. Improving these learned policies requires a separately validated training experiment with time-consistent rewards and discounting, controlled loss scales, and checkpoint selection on held-out greedy evaluation. Choice diversity alone is not evidence of better traffic control.
