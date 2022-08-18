# See https://stackoverflow.com/questions/53382383/makefile-cant-use-conda-activate
SHELL=/bin/bash
CONDA_ACTIVATE=source $$(conda info --base)/etc/profile.d/conda.sh ; conda activate ; conda activate
define lower 
$(shell echo $(1) | tr A-Z a-z)
endef

EXPERIMENTS=gs://vcm-ml-experiments/spencerc
CLIMATES = minus-4K unperturbed plus-4K plus-8K

SEEDS = 0 1 2 3

# Preparation steps
C384_SFC_DATA_ROOT=$(EXPERIMENTS)/2022-06-14-C384-sfc_data-initial-conditions
C384_AREA=$(C384_SFC_DATA_ROOT)/area/area
PATCHED_RESTART_FILE_DESTINATION=$(EXPERIMENTS)/2022-06-14-C48-snoalb-patched-restart-files

C48_REFERENCE_ROOT_minus-4K=gs://vcm-ml-raw-flexible-retention/2021-01-04-1-year-C384-FV3GFS-simulations
C48_REFERENCE_ROOT_unperturbed=gs://vcm-ml-raw-flexible-retention/2021-01-04-1-year-C384-FV3GFS-simulations
C48_REFERENCE_ROOT_plus-4K=gs://vcm-ml-raw-flexible-retention/2021-01-04-1-year-C384-FV3GFS-simulations
C48_REFERENCE_ROOT_plus-8K=gs://vcm-ml-raw-flexible-retention/2022-06-02-two-year-C384-FV3GFS-simulations

NUDGED_RUN_START_DATE=20170801.010000
PROGNOSTIC_RUN_START_DATE=20180801.000000

# Nudged runs
PRESCRIBER_REFERENCE_ROOT_minus-4K=gs://vcm-ml-intermediate/2021-04-30-nudge-to-25-km-prescriber-datasets
PRESCRIBER_REFERENCE_ROOT_unperturbed=gs://vcm-ml-intermediate/2021-04-30-nudge-to-25-km-prescriber-datasets
PRESCRIBER_REFERENCE_ROOT_plus-4K=gs://vcm-ml-intermediate/2021-04-30-nudge-to-25-km-prescriber-datasets
PRESCRIBER_REFERENCE_ROOT_plus-8K=gs://vcm-ml-intermediate/2022-06-14-nudge-to-25-km-prescriber-datasets

# ML training
TRAINING_DATA=gs://vcm-ml-experiments/spencerc/2022-06-28/n2f-25km-tapered-25-snoalb-nudging-tendencies-and-fluxes.zarr
TRAIN_ROOT=gs://vcm-ml-experiments/spencerc/2022-06-20-nudge-to-25-km-ml-models
FLUXES_RF_BASE=$(TRAIN_ROOT)/fluxes-rf-transmissivity-snoalb
FLUXES_RF_DERIVED=$(TRAIN_ROOT)/fluxes-rf-transmissivity-snoalb-derived
TQ_NN=$(TRAIN_ROOT)/tq-nn-snoalb-tapered-clipped-25

# Figures
FIGURES = figure-01 figure-02 figure-03 figure-04 figure-05 figure-06 figure-07 figure-08 figure-09 figure-10 figure-11 figure-12 figure-13 figure-S01 figure-S02 table-02 table-climate-change

create_environment:
	make -C software/fv3net-ml-corrected/fv3net update_submodules && \
		make -C software/fv3net-ml-corrected/fv3net create_environment && \
		( $(CONDA_ACTIVATE) fv3net ; pip install faceted==0.2.1 ; pip install nc-time-axis==1.4.1 ; pip install proplot==0.9.5 ; pip install seaborn==0.11.2 ; pip install xhistogram==0.3.1 )


# Patch the maximum snow albedo in restart files to address a coarse-graining error that
# enters the initial conditions.
initial_conditions: $(addprefix patch_snoalb_in_initial_conditions_, $(CLIMATES))
initial_conditions_%:
	python workflows/scripts/patch_snoalb.py \
		$(C384_SFC_DATA_ROOT)/$*/sfc_data \
		$(C384_AREA) \
		$(C48_REFERENCE_ROOT_$*)/$*/C384-to-C48-restart-files \
		$(PATCHED_RESTART_FILE_DESTINATION)/$* \
		$(NUDGED_RUN_START_DATE) $(PROGNOSTIC_RUN_START_DATE)


# Nudged runs
prescriber_reference: $(addprefix generate_prescriber_reference_, $(CLIMATES))
prescriber_reference_%:
	python workflows/scripts/generate_prescriber_reference_dataset.py \
		$(C48_REFERENCE_ROOT_$*)/$*/C384-to-C48-diagnostics/gfsphysics_15min_coarse.zarr \
		$(PRESCRIBER_REFERENCE_ROOT_$*)/$*/prescriber_reference.zarr


NUDGED_RUN_NAME_minus-4K=minus-4k-snoalb
NUDGED_RUN_NAME_unperturbed=unperturbed-snoalb
NUDGED_RUN_NAME_plus-4K=plus-4k-snoalb
NUDGED_RUN_NAME_plus-8K=updated-plus-8k-snoalb

NUDGED_RUN_CONFIG_minus-4K=workflows/nudged-runs/minus-4k.yaml
NUDGED_RUN_CONFIG_unperturbed=workflows/nudged-runs/unperturbed.yaml
NUDGED_RUN_CONFIG_plus-4K=workflows/nudged-runs/plus-4k.yaml
NUDGED_RUN_CONFIG_plus-8K=workflows/nudged-runs/updated-plus-8k.yaml
nudged_runs: $(addprefix nudged_run_, $(CLIMATES))
nudged_run_%: deploy_nudged_or_baseline
	workflows/scripts/run-nudged.sh \
		$(NUDGED_RUN_NAME_$*) \
		$(C48_REFERENCE_ROOT_$*)/$*/C384-to-C48-restart-files \
		$(NUDGED_RUN_CONFIG_$*)


BASELINE_RUN_NAME_minus-4K=minus-4k-snoalb
BASELINE_RUN_NAME_unperturbed=unperturbed-snoalb
BASELINE_RUN_NAME_plus-4K=plus-4k-snoalb
BASELINE_RUN_NAME_plus-8K=updated-plus-8k-snoalb
baseline_runs: $(addprefix baseline_run_, $(CLIMATES))
baseline_run_%: deploy_nudged_or_baseline
	workflows/scripts/run-baseline.sh \
		$(BASELINE_RUN_NAME_$*) \
		$(PATCHED_RESTART_FILE_DESTINATION)/$* \
		workflows/baseline-runs/$(call lower,$*).yaml


# ML training
training_dataset:
	python ./notebooks/generate_training_dataset.py $(TRAINING_DATA)


train_base_radiative_flux_model: deploy_ml_corrected
	./workflows/scripts/train-rf.sh \
		workflows/ml-training/fluxes-rf-base.yaml \
		workflows/ml-training/training-data-config.yaml  \
		$(FLUXES_RF_BASE)


create_derived_radiative_flux_model: deploy_ml_corrected
	./workflows/scripts/create-derived-model.sh \
		$(abspath workflows/ml-training/fluxes-rf-derived.yaml) \
		$(FLUXES_RF_DERIVED)


train_nudging_tendency_networks: $(addprefix train_nudging_tendency_networks_, $(SEEDS))
train_nudging_tendency_networks_%: deploy_ml_corrected
	./workflows/scripts/train-nn.sh \
		workflows/ml-training/tq-nn-training-config.yaml \
		workflows/ml-training/training-data-config.yaml  \
		$* \
		$(TQ_NN)


# ML-corrected runs
ml_corrected_runs: $(addprefix ml_corrected_run_, $(CLIMATES))
ml_corrected_run_%: deploy_ml_corrected
	./workflows/scripts/run-ml-corrected.sh \
		ml-corrected-updated-v3-$(call lower,$*) \
		$(PATCHED_RESTART_FILE_DESTINATION)/$* \
		workflows/ml-corrected-runs/$(call lower,$*).yaml \
		$(TQ_NN) \
		"0 1 2 3" \
		46 \
		$(FLUXES_RF_DERIVED)


extend_ml_corrected_runs: deploy_ml_corrected
	./workflows/scripts/restart.sh gs://vcm-ml-experiments/spencerc/2022-06-30/n2f-25km-ml-corrected-updated-v3-minus-4k-seed-1/fv3gfs_run 146
	./workflows/scripts/restart.sh gs://vcm-ml-experiments/spencerc/2022-06-30/n2f-25km-ml-corrected-updated-v3-unperturbed-seed-1/fv3gfs_run 146
	./workflows/scripts/restart.sh gs://vcm-ml-experiments/spencerc/2022-06-30/n2f-25km-ml-corrected-updated-v3-plus-4k-seed-1/fv3gfs_run 146
	./workflows/scripts/restart.sh gs://vcm-ml-experiments/spencerc/2022-06-30/n2f-25km-ml-corrected-updated-v3-plus-8k-seed-1/fv3gfs_run 146


# Post-processing and figure creation
post_process_runs:
	python post_processing.py
	python metrics.py
	python diurnal_cycle.py
	python imerg_diurnal_cycle.py
	python offline_r2.py


create_figures: $(addprefix execute_notebook_, $(FIGURES))


execute_notebook_%:
	jupyter nbconvert --to notebook --execute notebooks/$**.ipynb


# Workflow configuration
kustomize:
	./install_kustomize.sh 3.10.0


deploy_nudged_or_baseline: kustomize
	./kustomize build software/fv3net-nudged-or-baseline | kubectl apply -f -


deploy_ml_corrected: kustomize
	./kustomize build software/fv3net-ml-corrected | kubectl apply -f -


# Code for the simulation on the left in Figure 2.  Note the ML models were
# trained on a different set of nudged runs.  These nudged runs differ only in
# that they used a different (biased) maximum snow albedo pattern.  This did not
# affect nudging tendencies in a material way, but for maximum reproducibility,
# we include the code used to generate these nudged runs and train those models
# here.  
nudged_runs_old: $(addprefix nudged_run_old_, $(CLIMATES))
nudged_run_old_%: deploy_old_ml_corrected
	workflows/legacy/scripts/run-nudged.sh \
	$(call lower,$*) \
	$(C48_REFERENCE_ROOT)/$*/C384-to-C48-restart-files \
	workflows/legacy/nudged-runs/$(call lower,$*).yaml


OLD_MINUS_4K_N2F_DATA=gs://vcm-ml-experiments/spencerc/2021-05-11/n2f-25km-minus-4k/fv3gfs_run
OLD_UNPERTURBED_N2F_DATA=gs://vcm-ml-experiments/spencerc/2021-05-11/n2f-25km-unperturbed/fv3gfs_run
OLD_PLUS_4K_N2F_DATA=gs://vcm-ml-experiments/spencerc/2021-05-11/n2f-25km-plus-4k/fv3gfs_run
OLD_PLUS_8K_N2F_DATA=gs://vcm-ml-experiments/spencerc/2021-08-11/n2f-25km-plus-8k/fv3gfs_run

MINUS_4K_25KM_DIAGNOSTICS=$(C48_REFERENCE_ROOT)/minus-4K/C384-to-C48-diagnostics/gfsphysics_15min_coarse.zarr
UNPERTURBED_25KM_DIAGNOSTICS=$(C48_REFERENCE_ROOT)/unperturbed/C384-to-C48-diagnostics/gfsphysics_15min_coarse.zarr
PLUS_4K_25KM_DIAGNOSTICS=$(C48_REFERENCE_ROOT)/plus-4K/C384-to-C48-diagnostics/gfsphysics_15min_coarse.zarr
PLUS_8K_25KM_DIAGNOSTICS=$(C48_REFERENCE_ROOT)/plus-8K/C384-to-C48-diagnostics/gfsphysics_15min_coarse.zarr

OLD_FLUXES_TRAINING_DATA=gs://vcm-ml-experiments/spencerc/2021-07-02/all-climate-radiative-flux-training-data-transmissivity-8k.zarr
OLD_TQ_NN=gs://vcm-ml-scratch/spencerc/2022-05-22/another-b22-like-tq-nn
OLD_TQ_NN_ENSEMBLE=gs://vcm-ml-experiments/spencerc/2021-05-11/n2f-25km-models/all-climate-8k-tq-fixed-ensemble
OLD_RF_BASE=gs://vcm-ml-experiments/spencerc/2021-05-11/n2f-25km-models/all-climate-8k-fluxes-transmissivity-base
OLD_RF_DERIVED=gs://vcm-ml-experiments/spencerc/2021-05-11/n2f-25km-models/all-climate-8k-fluxes-derived-rf-transmissivity


train_old_nudging_tendency_networks: deploy_old_ml_corrected
	./workflows/scripts/legacy/train-nn.sh \
		"$(OLD_MINUS_4K_N2F_DATA) $(OLD_UNPERTURBED_N2F_DATA) $(OLD_PLUS_4K_N2F_DATA) $(OLD_PLUS_8K_N2F_DATA)" \
		workflows/legacy/ml-training/tq-nn.yaml \
		workflows/ml-training/train.json \
		$(OLD_TQ_NN)


create_old_nudging_tendency_network_ensemble:
	./workflows/legacy/scripts/create-ensemble.sh $(OLD_TQ_NN) $(OLD_TQ_NN_ENSEMBLE)


# With the previous version of the code we only created a separate training
# dataset for the radiative fluxes.  We could read the nudging tendencies
# directly in from the run directories of the nudged runs.
old_radiative_flux_training_dataset:
	python workflows/legacy/scripts/generate_old_radiative_flux_training_dataset.py \
	 	--fine-res $(MINUS_4K_25KM_DIAGNOSTICS) $(UNPERTURBED_25KM_DIAGNOSTICS) $(PLUS_4K_25KM_DIAGNOSTICS) $(PLUS_8K_25KM_DIAGNOSTICS) \
	 	--coarse-res $(OLD_MINUS_4K_N2F_DATA)/state_after_timestep.zarr $(OLD_UNPERTURBED_N2F_DATA)/state_after_timestep.zarr $(OLD_PLUS_4K_N2F_DATA)/state_after_timestep.zarr $(OLD_PLUS_8K_N2F_DATA)/state_after_timestep.zarr \
	 	--timesteps workflows/ml-training/train.json workflows/ml-training/test.json \
	 	--output $(OLD_FLUXES_TRAINING_DATA)


train_old_fluxes_random_forest_base: deploy_old_ml_corrected
	./workflows/legacy/scripts/train-rf.sh \
	$(OLD_FLUXES_TRAINING_DATA) \
	workflows/legacy/ml-training/fluxes-rf-base.yaml \
	workflows/ml-training/train.json \
	$(OLD_RF_BASE)


create_old_fluxes_derived_model:
	./workflows/scripts/create-derived-model.sh $(abspath workflows/legacy/ml-training/fluxes-rf-derived.yaml) $(OLD_RF_DERIVED)


# Indeed in this case we ran the ML-corrected simulation with the patched
# maximum snow albedo in the initial conditions (unlike the nudged runs
# associated with this particular experiment, where the maximum snow albedo was
# not patched).  Note this uses the version of fv3net used to run the nudged and
# baseline simulations in this study, since it has a transmissivity model
# capability built in.
ensemble_ml_corrected_run_unperturbed: deploy_nudged_or_baseline
	./workflows/legacy/scripts/run-ensemble-ml-corrected.sh \
		ml-corrected-v1-ensemble-unperturbed \
		$(PATCHED_RESTART_FILE_DESTINATION)/unperturbed \
		workflows/legacy/ml-corrected-runs/unperturbed.yaml \
		$(OLD_TQ_NN_ENSEMBLE) \
		1 \
		$(OLD_RF_DERIVED)


deploy_old_ml_corrected: kustomize
	./kustomize build software/fv3net-old-ml-corrected | kubectl apply -f -


# Code for sensitivity study to neural network hyperparameters, i.e.
# training new models and running new ML-corrected simulations.
deploy_fv3net_2022_07_08: kustomize
	./kustomize build workflows/sensitivity-experiments/fv3net-2022-07-08 | kubectl apply -f -


deploy_fv3net_2022_07_08_ml_corrected: kustomize
	./kustomize build workflows/sensitivity-experiments/fv3net-2022-07-08-ml-corrected | kubectl apply -f -


sensitivity_training_data:
	python workflows/sensitivity-experiments/save_training_batches.py
	python workflows/sensitivity-experiments/save_validation_batches.py


TRAIN_ROOT_SENSITIVITY=gs://vcm-ml-experiments/spencerc/2022-07-08-trained-models
TQ_NN_CLR=$(TRAIN_ROOT_SENSITIVITY)/tq-nn-clr-clipped-25
train_nudging_tendency_networks_clr: $(addprefix train_nudging_tendency_networks_clr_seed_, $(SEEDS))
train_nudging_tendency_networks_clr_seed_%: deploy_fv3net_2022_07_08
  ./workflows/sensitivity-experiments/train-nn.sh \
    workflows/sensitivity-experiments/tq-nn-untapered-larger-capacity.yaml \
    workflows/sensitivity-experiments/training-data-config-netcdf.yaml  \
    workflows/sensitivity-experiments/validation-data-config-netcdf.yaml  \
    $* \
    $(TQ_NN_CLR)


FLUXES_RF_SENSITIVITY=$(TRAIN_ROOT_SENSITIVITY)/fluxes-rf-base
train_fluxes_rf_sensitivity: deploy_fv3net_2022_07_08
  ./workflows/sensitivity-experiments/train-rf.sh \
    workflows/sensitivity-experiments/fluxes-rf-base.yaml \
    workflows/sensitivity-experiments/training-data-config-netcdf.yaml  \
    workflows/sensitivity-experiments/validation-data-config-netcdf.yaml  \
    $(FLUXES_RF_SENSITIVITY)


FLUXES_RF_DERIVED_SENSITIVITY=$(TRAIN_ROOT_SENSITIVITY)/fluxes-rf-derived
create_fluxes_derived_model_sensitivity:
  ./workflows/scripts/create-derived-model.sh $(abspath workflows/sensitivity-experiments/fluxes-rf-derived.yaml) $(FLUXES_RF_SENSITIVITY)


ml_corrected_sensitivity_runs_v5: $(addprefix ml_corrected_sensitivity_run_v5_, $(CLIMATES))
ml_corrected_sensitivity_run_v5_%: deploy_fv3net_2022_07_08_ml_corrected
	./workflows/scripts/run-ml-corrected.sh \
		ml-corrected-updated-v5-$(call lower,$*) \
		$(PATCHED_RESTART_FILE_DESTINATION)/$* \
		workflows/sensitivity-experiments/$(call lower,$*).yaml \
		$(TQ_NN_CLR) \
		"0 1 2 3" \
		46 \
		$(FLUXES_RF_DERIVED_SENSITIVITY)


restart_ml_corrected_sensitivity_runs_seed_3: deploy_fv3net_2022_07_08_ml_corrected
  ./workflows/scripts/restart.sh gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-minus-4k-seed-3/fv3gfs_run 146
  ./workflows/scripts/restart.sh gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-unperturbed-seed-3/fv3gfs_run 146
  ./workflows/scripts/restart.sh gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-plus-4k-seed-3/fv3gfs_run 146
  ./workflows/scripts/restart.sh gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-plus-8k-seed-3/fv3gfs_run 146


# Requires fv3net-2022-07-08
sensitivity_metrics:
	python ./workflows/sensitivity-experiments/post_processing.py
	python ./workflows/sensitivity-experiments/metrics.py
	python ./workflows/sensitivity-experiments/offline_r2_capacity.py


TRAIN_ROOT_SENSITIVITY_2=gs://vcm-ml-experiments/spencerc/2022-08-12-trained-models
TQ_NN_CLR_TAPERED=$(TRAIN_ROOT_SENSITIVITY_2)/tq-nn-clr-clipped-tapered-25
train_nudging_tendency_networks_clr_tapered: $(addprefix train_nudging_tendency_networks_clr_tapered_seed_, $(SEEDS))
train_nudging_tendency_networks_clr_tapered_seed_%: deploy_fv3net_2022_07_08
  ./workflows/sensitivity-experiments/train-nn.sh \
    workflows/sensitivity-experiments/tq-nn-tapered-larger-capacity.yaml \
    workflows/sensitivity-experiments/training-data-config-netcdf.yaml  \
    workflows/sensitivity-experiments/validation-data-config-netcdf.yaml  \
    $* \
    $(TQ_NN_CLR_TAPERED)
