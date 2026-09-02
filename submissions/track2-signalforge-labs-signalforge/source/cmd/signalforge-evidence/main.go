package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/evidence"
)

type stringList []string

func (values *stringList) String() string { return fmt.Sprint([]string(*values)) }
func (values *stringList) Set(value string) error {
	*values = append(*values, value)
	return nil
}

func main() {
	var artifacts stringList
	var modelFiles stringList
	var datasetFiles stringList
	repo := flag.String("repo", ".", "repository root")
	output := flag.String("output", "", "manifest output path")
	check := flag.String("check", "", "existing manifest to verify for staleness")
	runtimeFile := flag.String("runtime", "", "optional RuntimeIdentity JSON")
	gpuFile := flag.String("gpu", "", "optional GPUIdentity JSON")
	flag.Var(&artifacts, "artifact", "repository artifact to hash; repeatable")
	flag.Var(&modelFiles, "model", "ModelIdentity JSON; repeatable")
	flag.Var(&datasetFiles, "dataset", "DatasetIdentity JSON; repeatable")
	flag.Parse()

	if *check != "" {
		manifest, err := evidence.Read(*check)
		if err != nil {
			fatal(err)
		}
		issues, err := evidence.Check(*repo, manifest)
		if err != nil {
			fatal(err)
		}
		if len(issues) > 0 {
			payload, _ := json.MarshalIndent(issues, "", "  ")
			fmt.Fprintln(os.Stderr, string(payload))
			os.Exit(1)
		}
		fmt.Println("evidence manifest is current")
		return
	}
	if *output == "" || len(artifacts) == 0 {
		fatal(fmt.Errorf("--output and at least one --artifact are required"))
	}
	var runtimeIdentity contracts.RuntimeIdentity
	if *runtimeFile != "" {
		if err := readJSON(*runtimeFile, &runtimeIdentity); err != nil {
			fatal(err)
		}
	}
	var gpuIdentity *contracts.GPUIdentity
	if *gpuFile != "" {
		gpuIdentity = &contracts.GPUIdentity{}
		if err := readJSON(*gpuFile, gpuIdentity); err != nil {
			fatal(err)
		}
	}
	models := make([]contracts.ModelIdentity, 0, len(modelFiles))
	for _, path := range modelFiles {
		var identity contracts.ModelIdentity
		if err := readJSON(path, &identity); err != nil {
			fatal(err)
		}
		models = append(models, identity)
	}
	datasets := make([]contracts.DatasetIdentity, 0, len(datasetFiles))
	for _, path := range datasetFiles {
		var identity contracts.DatasetIdentity
		if err := readJSON(path, &identity); err != nil {
			fatal(err)
		}
		datasets = append(datasets, identity)
	}
	manifest, err := evidence.Generate(evidence.GenerateOptions{
		RepoRoot: *repo, Artifacts: artifacts, Runtime: runtimeIdentity,
		GPU: gpuIdentity, Models: models, Datasets: datasets,
	})
	if err != nil {
		fatal(err)
	}
	if err := evidence.Write(*output, manifest); err != nil {
		fatal(err)
	}
	fmt.Println(manifest.RunID)
}

func readJSON(path string, target any) error {
	payload, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	if err := json.Unmarshal(payload, target); err != nil {
		return fmt.Errorf("decode %s: %w", path, err)
	}
	return nil
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
