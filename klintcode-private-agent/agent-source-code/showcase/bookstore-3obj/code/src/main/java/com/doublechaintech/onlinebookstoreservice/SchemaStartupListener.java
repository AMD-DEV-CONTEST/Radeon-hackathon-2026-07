package com.doublechaintech.onlinebookstoreservice;

import io.teaql.core.UserContext;
import io.teaql.core.meta.EntityMetaFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

@Component
public class SchemaStartupListener implements CommandLineRunner {
    private static final Logger log = LoggerFactory.getLogger(SchemaStartupListener.class);

    @Autowired 
    private EntityMetaFactory factory;

    @Override
    public void run(String... args) throws Exception {
        log.info("SchemaStartupListener skipped for this version of teaql.");
    }
}